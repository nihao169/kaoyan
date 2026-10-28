"""Attach reviewed-layout original samples to demo drafts, without publishing teaching content."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from sqlalchemy import select
from app import models as m
from app.seed import DATA
from app.config import ROOT
from app.documents import store, parse_document
from app.db import SessionLocal


def attach():
    with SessionLocal.begin() as db:
        for i,item in enumerate(DATA):
            source=db.scalar(select(m.Source).where(m.Source.title==f"原创示例讲义 · {item['topic']}"))
            if not source or not db.get(m.Organization,source.org_id).is_demo: continue
            version=db.scalar(select(m.SourceVersion).where(m.SourceVersion.source_id==source.id,m.SourceVersion.status=='draft'))
            if not version or db.scalar(select(m.SourceDocument.id).where(m.SourceDocument.version_id==version.id)): continue
            path=ROOT/'docs/samples'/f'politics-{i+1:02d}-v1.pdf'
            doc=m.SourceDocument(version_id=version.id,filename=path.name,original_key=store(path.read_bytes(),'.pdf'))
            db.add(doc);db.flush();parse_document(db,version.id)
    print('Original sample pages attached to drafts; teacher confirmation still required.')


if __name__=='__main__': attach()
