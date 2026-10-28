"""Evaluate actual local embeddings on a separately initialized/published acceptance DB."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from sqlalchemy import select
from app.config import ROOT
from app.db import SessionLocal
from app import models as m
from app.auth import Context
from app.search import hybrid, fingerprint


def main():
    cases=json.loads((ROOT/'docs/evaluation-cases.json').read_text(encoding='utf-8'))
    rows=[]
    with SessionLocal() as db:
        user=db.scalar(select(m.User).where(m.User.username=='student'))
        member=db.scalar(select(m.Membership).where(m.Membership.user_id==user.id))
        roles=list(db.scalars(select(m.RoleAssignment).where(m.RoleAssignment.membership_id==member.id)))
        ctx=Context(user,member,roles,None)
        for case in cases:
            if 'query' not in case: continue
            results=hybrid(db,ctx,case['query'])
            rows.append({'id':case['id'],'hit':any(case['topic'] in r['source_title'] for r in results),
                         'sources':[r['source_title'] for r in results]})
    recall=sum(r['hit'] for r in rows)/len(rows)
    output=ROOT/'.runtime/retrieval-evaluation.json'
    output.write_text(json.dumps({'model':fingerprint(),'recall_at_5':recall,'cases':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Actual local embedding Recall@5:',recall)
    if recall<0.9: raise SystemExit('Recall@5 threshold not reached')


if __name__=='__main__': main()
