"""Search the complete extracted corpus in the authorized project, then cite exact spans."""
from dataclasses import dataclass
from collections import Counter
import math
import re
from ..citation_text import quote_offset
from ..config import settings

WORDS = re.compile(r'[a-z0-9]+|[\u3400-\u9fff]+', re.I)
PAGES = re.compile(r'^\[第 (\d+) 页\]\n', re.M)


def terms(text):
    for word in WORDS.findall(text.casefold()):
        if '\u3400' <= word[0] <= '\u9fff':
            yield from word
            yield from (word[i:i+2] for i in range(len(word)-1))
        else:
            yield word


@dataclass(frozen=True)
class Passage:
    material: object
    start: int
    end: int

    @property
    def text(self):
        return self.material.text[self.start:self.end]


def passages(material):
    # Overlap preserves phrases crossing a chunk boundary; every character is indexed.
    page_boundaries = [match.start() for match in PAGES.finditer(material.text)] if original_pdf(material) else []
    bounds = sorted({0, *page_boundaries, len(material.text)})
    for lower, upper in zip(bounds, bounds[1:]):
        for start in range(lower, upper, 640):
            yield Passage(material, start, min(start+880, upper))
            if start+880 >= upper:
                break


def retrieve(materials, query, limit=12, preferred=None, fallback=False):
    chunks = [item for material in materials for item in passages(material)]
    query_terms = Counter(terms(query[:8000]))
    counts = [Counter(t for t in terms(chunk.text) if t in query_terms) for chunk in chunks]
    df = Counter(t for count in counts for t in count)
    weights = {t: math.log(1 + (len(chunks)-n+.5)/(n+.5)) *
               (2.0 if len(t)>1 else .25) for t,n in df.items()}
    scores = [sum(weights[t]*n/(n+1) for t,n in count.items()) for count in counts]
    ordered = sorted(range(len(chunks)), key=lambda i: (
        -scores[i] * (1.15 if chunks[i].material.id == preferred else 1),
        chunks[i].material.id != preferred, i))
    require_word = any(len(t)>1 for t in query_terms)
    matches = [chunks[i] for i in ordered if scores[i] > 0 and
               (not require_word or any(len(t)>1 for t in counts[i]))]
    if not matches and fallback:
        matches = [chunks[i] for i in ordered[:limit]]
    return matches[:limit]


def original_pdf(material):
    path = settings.data_dir / 'v2-originals' / material.project_id / (material.id + '.pdf')
    return path if path.is_file() else None


def location(material, start, end):
    text = material.text
    page = None
    if original_pdf(material):
        pages = list(PAGES.finditer(text))
        for index, marker in enumerate(pages):
            boundary = pages[index+1].start() if index+1 < len(pages) else len(text)
            if marker.start() <= start < end <= boundary:
                page = int(marker[1])
                break
    return {'material_id': material.id, 'title': material.title, 'sha256': material.sha256,
            'source_version_id': material.source_version_id, 'start': start, 'end': end,
            'line_start': text.count('\n', 0, start)+1,
            'line_end': text.count('\n', 0, end-1)+1, 'page': page}


def verify(sent, current, quote, material_id=None):
    if not isinstance(quote, str) or not 8 <= len(quote) <= 600:
        return None
    versions = {m.id: m for m in current}
    for chunk in sent:
        mid = chunk.material.id
        material = versions.get(mid)
        if (not material or material.sha256 != chunk.material.sha256 or
                (material_id is not None and mid != material_id)):
            continue
        offset = quote_offset(chunk.text, quote)
        if offset >= 0:
            start = chunk.start+offset
            return {**location(material, start, start+len(quote)), 'quote': quote}
    return None
