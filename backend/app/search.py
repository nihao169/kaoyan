"""Permission-filtered keyword + local multilingual dense retrieval; no result cache."""
import threading
import re
import json
from functools import lru_cache
from sqlalchemy import select, delete
from . import models as m
from .config import settings

_lock = threading.Lock()


class SearchUnavailable(Exception):
    pass


@lru_cache(maxsize=2)
def encoder(model, revision, local_only):
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(model, revision=revision, cache_folder=str(settings.embedding_cache_dir),
                                   local_files_only=local_only, device='cpu')
    except Exception as exc:
        raise SearchUnavailable('EMBEDDING_MODEL_UNAVAILABLE') from exc


def fingerprint():
    return settings.embedding_model + '@' + resolved_revision()


def resolved_revision():
    manifest = settings.embedding_cache_dir / 'revision.json'
    if settings.embedding_revision == 'main' and manifest.exists():
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('model') == settings.embedding_model:
            return data['revision']
    return settings.embedding_revision


def encode_segments(text):
    model = encoder(settings.embedding_model, resolved_revision(), settings.embedding_local_only)
    tokens = model.tokenizer.encode(text, add_special_tokens=False, truncation=False, verbose=False)
    size = max(16, min(model.max_seq_length - 2, 120))
    segments = [model.tokenizer.decode(tokens[i:i+size]) for i in range(0, len(tokens), size-16)] or ['']
    with _lock:
        return model.encode(segments, normalize_embeddings=True, show_progress_bar=False).tolist()


def build_index(db, version_id):
    for chunk in db.scalars(select(m.SourceChunk).where(m.SourceChunk.version_id == version_id)):
        row = db.scalar(select(m.ChunkEmbedding).where(m.ChunkEmbedding.chunk_id == chunk.id,
                                                       m.ChunkEmbedding.model_revision == fingerprint()))
        if not row:
            db.add(m.ChunkEmbedding(chunk_id=chunk.id, model_revision=fingerprint(), vectors=encode_segments(chunk.text)))


def process_index(version_id):
    from .db import SessionLocal
    with SessionLocal() as db:
        revision = fingerprint()
        chunks = [(c.id, c.text) for c in db.scalars(select(m.SourceChunk).where(m.SourceChunk.version_id == version_id))]
        existing = set(db.scalars(select(m.ChunkEmbedding.chunk_id).where(m.ChunkEmbedding.chunk_id.in_([c[0] for c in chunks]), m.ChunkEmbedding.model_revision == revision)))
    # All inference runs outside a database transaction.
    prepared = [(cid, text, encode_segments(text)) for cid,text in chunks if cid not in existing]
    if fingerprint() != revision:
        raise SearchUnavailable('MODEL_CONFIGURATION_CHANGED')
    with SessionLocal.begin() as db:
        for cid, text, vectors in prepared:
            chunk = db.get(m.SourceChunk, cid)
            if chunk and chunk.text == text and not db.scalar(select(m.ChunkEmbedding.id).where(m.ChunkEmbedding.chunk_id == cid, m.ChunkEmbedding.model_revision == revision)):
                db.add(m.ChunkEmbedding(chunk_id=cid, model_revision=revision, vectors=vectors))


def hybrid(db, ctx, query, knowledge_id=None, version_id=None):
    from .content import retrieve
    # retrieve performs permission/version filtering before any vectors or text are scored.
    candidates = retrieve(db, ctx, '', knowledge_id, version_id, limit=None)
    if not candidates:
        return []
    query_vectors = encode_segments(query)
    ranked = []
    for item in candidates:
        embedding = db.scalar(select(m.ChunkEmbedding).where(m.ChunkEmbedding.chunk_id == item['chunk_id'],
                                                              m.ChunkEmbedding.model_revision == fingerprint()))
        if not embedding:
            raise SearchUnavailable('INDEX_NOT_READY')
        semantic = max(sum(a*b for a,b in zip(q,v)) for q in query_vectors for v in embedding.vectors)
        terms = re.findall(r'[\u4e00-\u9fff]|[a-zA-Z]+', query.lower())
        lexical = sum(t in item['text'].lower() for t in terms) / max(1, len(terms))
        ranked.append((semantic, lexical, item))
    semantic_order = {r[2]['chunk_id']: i+1 for i,r in enumerate(sorted(ranked, key=lambda r:-r[0]))}
    lexical_order = {r[2]['chunk_id']: i+1 for i,r in enumerate(sorted(ranked, key=lambda r:-r[1]))}
    for semantic, lexical, item in ranked:
        item['score'] = 1/(60+semantic_order[item['chunk_id']]) + 1/(60+lexical_order[item['chunk_id']])
        item['retrieval'] = 'hybrid'
    return sorted([r[2] for r in ranked], key=lambda r:-r['score'])[:5]


def expand_context(db, ctx, evidence):
    from .content import retrieve
    result = list(evidence)
    seen = {e['chunk_id'] for e in result}
    for match in evidence:
        for neighbor in retrieve(db, ctx, '', version_id=match['version_id'], limit=None):
            if abs(neighbor['position']-match['position']) == 1 and neighbor['chunk_id'] not in seen:
                result.append(neighbor)
                seen.add(neighbor['chunk_id'])
    return result
