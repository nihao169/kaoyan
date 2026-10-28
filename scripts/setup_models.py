"""Explicit, resumable public model setup; runtime inference never downloads silently."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.config import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--reindex', action='store_true')
    args = parser.parse_args()
    if args.download:
        from huggingface_hub import HfApi, snapshot_download
        revision = HfApi().model_info(settings.embedding_model, revision=settings.embedding_revision).sha
        snapshot_download(settings.embedding_model, revision=revision, cache_dir=str(settings.data_dir / 'models'),
            max_workers=2, ignore_patterns=['onnx/*', 'openvino/*', '*.h5', '*.ot', '*.msgpack', '*.bin'])
        path = settings.data_dir / 'models' / 'revision.json'
        path.write_text(json.dumps({'model':settings.embedding_model, 'revision':revision}), encoding='utf-8')
    from app.search import encode_segments, fingerprint, build_index
    vectors = encode_segments('实践是认识的来源')
    print('Local embedding ready:', fingerprint(), 'dimensions:', len(vectors[0]))
    if args.reindex:
        from app.db import SessionLocal
        from app import models as m
        from sqlalchemy import select
        with SessionLocal.begin() as db:
            for version in db.scalars(select(m.SourceVersion).where(m.SourceVersion.status.in_(['published', 'pending', 'draft']))):
                build_index(db, version.id)
        print('Indexes rebuilt; historical versions preserved.')


if __name__ == '__main__':
    main()
