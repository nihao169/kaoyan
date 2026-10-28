"""Originals and fixed-layout previews. No OCR and no execution of document instructions."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile
from sqlalchemy import select, delete
from .config import settings
from . import models as m
from .ports import LocalFileStore


class DocumentError(Exception):
    pass


def store(body, suffix):
    key = hashlib.sha256(body).hexdigest() + suffix
    root = settings.data_dir / 'files'
    root.mkdir(parents=True, exist_ok=True)
    (root / key).write_bytes(body)
    return key


def parse_document(db, version_id, release_transaction=False):
    import pymupdf as fitz
    doc = db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id == version_id))
    version = db.get(m.SourceVersion, version_id)
    if doc.state == 'parsed' and doc.preview_key and db.scalar(select(m.SourceChunk.id).where(m.SourceChunk.version_id == version_id)):
        return
    original_key = doc.original_key
    path = settings.data_dir / 'files' / original_key
    if release_transaction:
        db.commit()
    try:
        if path.suffix == '.docx':
            # LibreOffice conversion preserves pagination; never label reflowed text as an original page.
            converter = settings.document_converter or shutil.which('soffice')
            if not converter:
                conventional = Path('C:/Program Files/LibreOffice/program/soffice.exe')
                converter = str(conventional) if conventional.exists() else None
            if not converter:
                from .config import ROOT
                portable = ROOT / '.runtime/libreoffice/program/soffice.exe'
                converter = str(portable) if portable.exists() else None
            if not converter:
                raise DocumentError('DOCX_CONVERTER_REQUIRED')
            temp_root = settings.data_dir / 'document-temp'
            temp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=temp_root, ignore_cleanup_errors=True) as tmp:
                output = Path(tmp)
                result = subprocess.run([converter, '-env:UserInstallation=' + (output / 'profile').as_uri(),
                    '--headless', '--convert-to', 'pdf', '--outdir', tmp, str(path.resolve())],
                    capture_output=True, timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                pdf = output / (path.stem + '.pdf')
                if result.returncode or not pdf.exists():
                    raise DocumentError('DOCX_CONVERSION_FAILED')
                preview_key = store(pdf.read_bytes(), '.pdf')
        else:
            preview_key = original_key
        with fitz.open(settings.data_dir / 'files' / preview_key) as pdf:
            if pdf.needs_pass:
                raise DocumentError('PDF_ENCRYPTED')
            if len(pdf) > 300:
                raise DocumentError('DOCUMENT_PAGE_LIMIT')
            pages = []
            for i, page in enumerate(pdf):
                blocks = [{'bbox': list(b[:4]), 'text': b[4].strip()} for b in page.get_text('blocks') if b[4].strip()]
                if not blocks or (sum(len(b['text'].strip()) for b in blocks) < 30 and page.get_images()):
                    raise DocumentError('SCANNED_PAGE_OCR_UNSUPPORTED')
                pages.append({'number': i + 1, 'width': page.rect.width, 'height': page.rect.height, 'blocks': blocks})
            if not pages:
                raise DocumentError('DOCUMENT_EMPTY')
        if release_transaction:
            db.refresh(doc)
            db.refresh(version)
            if doc.original_key != original_key or version.status != 'draft':
                raise DocumentError('DOCUMENT_CHANGED')
        doc.preview_key = preview_key
        # Delete dependent vectors first; source chunks are mutable only before publication.
        ids = select(m.SourceChunk.id).where(m.SourceChunk.version_id == version.id)
        db.execute(delete(m.ChunkEmbedding).where(m.ChunkEmbedding.chunk_id.in_(ids)))
        db.execute(delete(m.SourceChunk).where(m.SourceChunk.version_id == version.id))
        texts = []
        for page in pages:
            text = '\n\n'.join(b['text'] for b in page['blocks'])
            texts.append(text)
            db.add(m.SourceChunk(version_id=version.id, position=page['number'], heading=f"第 {page['number']} 页", text=text))
        version.text = '\n\n'.join(texts)
        version.file_key = LocalFileStore(settings.data_dir / 'files').put(version.text.encode('utf-8'))
        version.sha256 = hashlib.sha256(version.text.encode('utf-8')).hexdigest()
        doc.pages, doc.state, doc.error_code, doc.confirmed = pages, 'parsed', '', False
        source = db.get(m.Source, version.source_id)
        db.add(m.Job(org_id=source.org_id, owner_id=source.owner_id, kind='index', resource_id=version.id))
    except DocumentError:
        raise
    except subprocess.TimeoutExpired:
        raise DocumentError('DOCX_CONVERSION_TIMEOUT')
    except Exception as exc:
        raise DocumentError('DOCUMENT_INVALID') from exc


def document_view(doc):
    return {'id': doc.id, 'filename': doc.filename, 'state': doc.state, 'error_code': doc.error_code,
            'confirmed': doc.confirmed, 'pages': doc.pages,
            'original_url': f'/api/v1/sources/versions/{doc.version_id}/original',
            'preview_url': f'/api/v1/sources/versions/{doc.version_id}/preview' if doc.preview_key else None}
