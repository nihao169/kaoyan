"""Explicit real-provider contract smoke check; prints no credentials."""
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.config import settings
from app.v2.tutor import execute

secrets=json.loads((ROOT/'.runtime/v2-secrets.json').read_text(encoding='utf-8-sig'))
settings.deeptutor_url='http://127.0.0.1:18001'
settings.deeptutor_bridge_secret=secrets['bridge_secret']
events=[]
def record(value):
    events.append(value.get('type'))
    print(json.dumps({'event':value.get('type'),'code':value.get('error_code',''),'message':value.get('message','')},ensure_ascii=False),flush=True)
result=asyncio.run(execute('contract-check:'+uuid4().hex,'请仅回答“基础服务连接成功”。','chat',str(uuid4()),record))
print(json.dumps({'provider':'real DeepTutor','text':result,'events':sorted(set(events))},ensure_ascii=False))
