import io
import pytest
from sqlalchemy import select, func
from app import models as m
from app.db import SessionLocal
from app.worker import tick
from app.documents import parse_document
from app.ai_services import process_request, completion
from app.ai import WorkflowError
from app.config import settings
from conftest import checked, publish_all as publish_legacy, create_task, save_and_submit


def publish_all(teacher):
    sources=publish_legacy(teacher)
    me=checked(teacher,'/me')
    # Legacy auxiliary-AI regressions explicitly grant these controlled fixtures
    # as enabled teacher materials; publication alone is no longer AI consent.
    with SessionLocal.begin() as db:
        for source in sources:
            db.add(m.SourceActivation(version_id=source['id'],org_id=me['org_id'],teacher_id=me['id']))
    return sources


@pytest.mark.parametrize('purpose',['question','lesson'])
def test_auxiliary_ai_cannot_use_unenabled_legacy_material(clients,monkeypatch,purpose):
    student,teacher,_=clients
    publish_legacy(teacher)
    monkeypatch.setattr(settings,'model_api_key','explicit-controlled-key')
    with SessionLocal() as db:
        q=db.scalar(select(m.QuestionVersion).where(m.QuestionVersion.kind=='single'))
        qid,kid=q.id,q.knowledge_id
    if purpose=='question':
        a=create_task(student,qid)
        request=checked(student,'/ai/requests','POST',{'purpose':'question','attempt_id':a['id']},status=202)
    else:
        request=checked(teacher,'/ai/requests','POST',{'purpose':'lesson','knowledge_id':kid},status=202)
    def forbidden(*args,**kwargs):
        pytest.fail('Model must not be called without enabled evidence')
    monkeypatch.setattr('app.ai_services.completion',forbidden)
    with pytest.raises(WorkflowError) as error:
        process_request(request['id'])
    assert error.value.code==('SOURCE_NOT_ENABLED' if purpose=='question' else 'NO_EVIDENCE')


def test_pdf_original_review_and_historical_preview(clients):
    import pymupdf as fitz
    student, teacher, _ = clients
    knowledge = checked(teacher, '/catalog')['knowledge'][0]['id']
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 100), 'Original teaching sample: conditions and evidence.')
        body = pdf.tobytes()
    response = teacher.post('/api/v1/content/sources/upload', data={'knowledge_id':knowledge, 'rights':'original test sample'},
        files={'file':('sample.pdf', body, 'application/pdf')})
    assert response.status_code == 202, response.text
    version_id = response.json()['data']['id']
    checked(teacher, '/content/sources/'+version_id+'/submit', 'POST', {'note':'not parsed'}, status=409)
    with SessionLocal.begin() as db:
        parse_document(db, version_id)
    info = checked(teacher, f'/sources/versions/{version_id}/document')
    assert info['state'] == 'parsed' and len(info['pages']) == 1
    assert teacher.get(info['preview_url']).headers['content-type'] == 'application/pdf'
    assert teacher.get(f'/api/v1/sources/versions/{version_id}/pages/1').content.startswith(b'\x89PNG')
    assert student.get(info['original_url']).status_code == 404
    checked(teacher, f'/documents/{version_id}/confirm','POST')
    checked(teacher, '/content/sources/'+version_id+'/submit', 'POST', {'note':'reviewed'})
    assert checked(teacher, f'/sources/versions/{version_id}/document')['confirmed'] is True


def test_scanned_pdf_fails_without_fabricated_text(clients):
    import pymupdf as fitz
    _, teacher, _ = clients
    knowledge=checked(teacher, '/catalog')['knowledge'][0]['id']
    with fitz.open() as pdf:
        page=pdf.new_page()
        # A scanned page may still have a machine-readable page number.
        import base64
        page.insert_image(fitz.Rect(50,80,500,700),stream=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZp8AAAAASUVORK5CYII='))
        page.insert_text((50,40),'1')
        body=pdf.tobytes()
    r=teacher.post('/api/v1/content/sources/upload',data={'knowledge_id':knowledge,'rights':'test'},files={'file':('scan.pdf',body)})
    version=r.json()['data']['id']
    for _ in range(10):
        if not tick(): break
    result=checked(teacher,f'/sources/versions/{version}/document')
    assert result['state']=='failed' and result['error_code']=='SCANNED_PAGE_OCR_UNSUPPORTED'
    checked(teacher,'/content/sources/'+version+'/submit','POST',{'note':'cannot publish'},status=409)


def test_cause_rematches_card_preserves_history_and_teacher_scope(clients):
    student, teacher, admin=clients
    publish_all(teacher)
    with SessionLocal() as db:
        q=db.scalar(select(m.QuestionVersion).where(m.QuestionVersion.kind=='single'))
        qid=q.id
    attempt=save_and_submit(student,create_task(student,qid),['D'])
    r=checked(student,'/remediations')[0]
    checked(student,f'/remediations/{r["id"]}/cause','POST',{'cause':'概念混淆'})
    first=checked(student,'/remediations')[0]['card']['id']
    checked(teacher,f'/teacher/remediations/{r["id"]}/cause','POST',{'cause':'论证表达'})
    second=checked(student,'/remediations')[0]['card']['id']
    assert first != second
    chain=checked(teacher,f'/teacher/attempts/{attempt["id"]}/learning-chain')
    assert len([e for e in chain['events'] if e['kind']=='cause_changed'])==2
    checked(admin,f'/teacher/remediations/{r["id"]}/cause','POST',{'cause':'审题'},status=403)


def test_referral_and_knowledge_status(clients):
    student, teacher, admin=clients
    publish_all(teacher)
    with SessionLocal() as db: qid=db.scalar(select(m.QuestionVersion.id))
    a=create_task(student,qid)
    r=checked(student,f'/attempts/{a["id"]}/referrals','POST',{'text':'需要核对条件'})
    checked(teacher,f'/teaching/referrals/{r["id"]}/resolve','POST',{'text':'请先核对材料中的主体和时间范围。'})
    assert checked(student,'/teaching/referrals')[0]['state']=='resolved'
    assert any(k['state']=='待诊断' for k in checked(student,'/knowledge/status'))
    checked(admin,'/ai/status')
    checked(student,'/ai/status',status=403)
    checked(admin,'/ai/connection-test','POST',status=503)


@pytest.mark.parametrize('purpose',['question','hint','cause','evaluation','lesson'])
def test_real_workflow_with_explicit_controlled_provider(clients,monkeypatch,purpose):
    student,teacher,_=clients
    publish_all(teacher)
    monkeypatch.setattr(settings,'model_api_key','controlled-key-never-real')
    with SessionLocal() as db:
        q=db.scalar(select(m.QuestionVersion).where(m.QuestionVersion.kind=='essay' if purpose=='evaluation' else m.QuestionVersion.kind=='single'))
        qid,knowledge=q.id,q.knowledge_id
    a=create_task(student,qid)
    if purpose in ('cause','evaluation'): a=save_and_submit(student,a,[] if purpose=='evaluation' else ['A'],response_text='原理与材料相联系')
    calls=[]
    def provider(messages,metrics):
        import json
        payload=json.loads(messages[-1]['content'])
        calls.append(payload)
        metrics['calls']=metrics.get('calls',0)+1
        if 'response' in payload:
            return {'supported':True,'conflict':False,'leaks_answer':False,'reason':'controlled verification'}
        return {'explanation':'依据审核资料，应先辨明概念和材料条件。','citations':[payload['evidence'][0]['chunk_id']],
                'candidate_cause':'概念混淆','dimensions':[],'reliable':True}
    monkeypatch.setattr('app.ai_services.completion',provider)
    body={'purpose':purpose,'attempt_id':a['id']} if purpose!='lesson' else {'purpose':'lesson','knowledge_id':knowledge}
    client=teacher if purpose=='lesson' else student
    r=checked(client,'/ai/requests','POST',body,status=202,idem='same-request')
    assert checked(client,'/ai/requests','POST',body,status=202,idem='same-request')['id']==r['id']
    process_request(r['id']);process_request(r['id'])
    result=checked(client,'/ai/requests')[0]
    assert result['state']=='succeeded' and result['result']['sources'] and len(calls)==2
    assert checked(student,'/attempts/'+a['id'])['evaluation']==a['evaluation']
    if purpose=='lesson':
        lesson=checked(teacher,'/teacher/lessons')[0]
        checked(teacher,'/teacher/lessons/'+lesson['id'],'PUT',{'text':'教师修订稿','revision':lesson['revision']})
        checked(teacher,'/teacher/lessons/'+lesson['id'],'PUT',{'text':'旧稿','revision':lesson['revision']},status=409)


@pytest.mark.parametrize('status,code',[(401,'MODEL_AUTH_FAILED'),(402,'MODEL_INSUFFICIENT_BALANCE'),(429,'MODEL_RATE_LIMIT'),(500,'MODEL_TEMPORARY_ERROR')])
def test_provider_error_mapping(monkeypatch,status,code):
    import httpx
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,*args,**kwargs): return httpx.Response(status)
    monkeypatch.setattr('app.ai_services.httpx.Client',Client)
    with pytest.raises(WorkflowError) as error: completion([], {})
    assert error.value.code==code


def test_docx_parser_real_conversion(clients,document_fixture):
    from pathlib import Path
    _,teacher,_=clients
    path=document_fixture/'sample.docx'
    knowledge=checked(teacher,'/catalog')['knowledge'][0]['id']
    r=teacher.post('/api/v1/content/sources/upload',data={'knowledge_id':knowledge,'rights':'original sample'},files={'file':('sample.docx',path.read_bytes())})
    version=r.json()['data']['id']
    with SessionLocal.begin() as db: parse_document(db,version)
    d=checked(teacher,f'/sources/versions/{version}/document')
    assert d['preview_url'] and d['pages']
    # LibreOffice chooses different CJK line breaks and block boundaries
    # depending on the installed Windows fonts.
    extracted = ''.join(''.join(block['text'].split())
                        for page in d['pages'] for block in page['blocks'])
    assert 'ZHIXING_DOCX_CONVERSION_CHECK' in extracted


@pytest.mark.parametrize('mode',['conflict','leak','invalid_citation','timeout'])
def test_ai_v2_rejection_recovery_and_score_integrity(clients,monkeypatch,mode):
    import json
    student,teacher,_=clients
    publish_all(teacher)
    monkeypatch.setattr(settings,'model_api_key','controlled-only')
    with SessionLocal() as db: qid=db.scalar(select(m.QuestionVersion.id).where(m.QuestionVersion.kind=='single'))
    a=create_task(student,qid)
    def provider(messages,metrics):
        data=json.loads(messages[-1]['content'])
        if mode=='timeout': raise WorkflowError('MODEL_TIMEOUT',True)
        if 'response' in data:
            return {'supported':True,'conflict':mode=='conflict','leaks_answer':mode=='leak','reason':'A is the answer; do not expose this verifier text'}
        return {'explanation':'Correct option A','candidate_cause':'待确认','citations':['fabricated'] if mode=='invalid_citation' else [data['evidence'][0]['chunk_id']]}
    monkeypatch.setattr('app.ai_services.completion',provider)
    request=checked(student,'/ai/requests','POST',{'purpose':'hint','attempt_id':a['id'],'level':1},status=202)
    for _ in range(12):
        tick()
    result=next(r for r in checked(student,'/ai/requests') if r['id']==request['id'])
    if mode in ('conflict','leak'):
        assert result['state']=='succeeded' and result['result']['reliable'] is False
        assert result['result']['sources']==[] and 'option A' not in str(result['result'])
    else:
        assert result['state']=='failed'
        assert result['error_code']==('INVALID_CITATION' if mode=='invalid_citation' else 'MODEL_TIMEOUT')
    assert checked(student,'/attempts/'+a['id'])['evaluation'] is None
    assert checked(student,'/attempts/'+a['id'])['hint_level'] == 0


def test_document_original_preview_in_backup(clients,document_fixture):
    from pathlib import Path
    from uuid import uuid4
    from app.config import ROOT
    from app.backup import create, validate
    _,teacher,_=clients
    body=(document_fixture/'sample.pdf').read_bytes()
    knowledge=checked(teacher,'/catalog')['knowledge'][0]['id']
    r=teacher.post('/api/v1/content/sources/upload',data={'knowledge_id':knowledge,'rights':'test'},files={'file':('original.pdf',body)})
    version=r.json()['data']['id']
    with SessionLocal.begin() as db: parse_document(db,version)
    backup=create(ROOT/'.runtime/backup-tests'/str(uuid4()))
    manifest=validate(backup)
    assert any(k.endswith('.pdf') for k in manifest['files'])


def test_migration_roundtrip_preserves_existing_learning(clients):
    from alembic import command
    from alembic.config import Config
    from app.config import ROOT
    student,teacher,_=clients
    publish_all(teacher)
    with SessionLocal() as db: qid=db.scalar(select(m.QuestionVersion.id).where(m.QuestionVersion.kind=='single'))
    a=save_and_submit(student,create_task(student,qid),['A'])
    cfg=Config(str(ROOT/'backend/alembic.ini'))
    command.downgrade(cfg,'4532821757bc')
    command.upgrade(cfg,'head')
    restored=checked(student,'/attempts/'+a['id'])
    assert restored['process']==a['process'] and restored['evaluation']==a['evaluation']


def test_source_revoked_during_ai_is_not_delivered(clients,monkeypatch):
    import json
    student,teacher,_=clients
    publish_all(teacher)
    monkeypatch.setattr(settings,'model_api_key','controlled-only')
    with SessionLocal() as db:
        q=db.scalar(select(m.QuestionVersion).where(m.QuestionVersion.kind=='single'));qid,version=q.id,q.source_version_id
    a=create_task(student,qid)
    def provider(messages,metrics):
        payload=json.loads(messages[-1]['content'])
        if 'response' in payload: return {'supported':True,'conflict':False,'leaks_answer':False,'reason':'controlled'}
        checked(teacher,f'/content/sources/{version}/withdraw','POST',{'note':'调用期间撤回测试'})
        return {'explanation':'不得交付这段结果','citations':[payload['evidence'][0]['chunk_id']]}
    monkeypatch.setattr('app.ai_services.completion',provider)
    r=checked(student,'/ai/requests','POST',{'purpose':'hint','attempt_id':a['id']},status=202)
    for _ in range(12): tick()
    result=next(x for x in checked(student,'/ai/requests') if x['id']==r['id'])
    assert result['state']=='failed' and result['error_code']=='CONTENT_UNAVAILABLE' and not result['result']


def test_background_conversion_releases_database_transaction(clients,monkeypatch,document_fixture):
    import shutil
    from pathlib import Path
    from types import SimpleNamespace
    from app.config import ROOT
    _,teacher,_=clients
    def convert(command,**kwargs):
        # This write would fail with BUSY/timeout if conversion retained its DB lock.
        with SessionLocal.begin() as db: db.add(m.AuditEvent(action='test.converter.database.unlocked'))
        output=Path(command[command.index('--outdir')+1])/(Path(command[-1]).stem+'.pdf')
        shutil.copy2(document_fixture/'sample.pdf',output)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('app.documents.subprocess.run',convert)
    knowledge=checked(teacher,'/catalog')['knowledge'][0]['id']
    r=teacher.post('/api/v1/content/sources/upload',data={'knowledge_id':knowledge,'rights':'test'},files={'file':('sample.docx',(document_fixture/'sample.docx').read_bytes())})
    version=r.json()['data']['id']
    for _ in range(30):
        if not tick(): break
    assert checked(teacher,f'/sources/versions/{version}/document')['state']=='parsed'


def test_background_index_inference_releases_database_transaction(clients,monkeypatch):
    from app import search
    original=search.encode_segments
    def inference(text):
        with SessionLocal.begin() as db: db.add(m.AuditEvent(action='test.embedding.database.unlocked'))
        return original(text)
    monkeypatch.setattr(search,'encode_segments',inference)
    _,teacher,_=clients
    for _ in range(30):
        if not tick(): break
    source=checked(teacher,'/content/sources')['items'][0]
    assert checked(teacher,'/content/indexes/'+source['id'])['state']=='ready'


def test_connection_test_releases_auth_transaction(clients,monkeypatch):
    _,_,admin=clients
    monkeypatch.setattr(settings,'model_api_key','controlled-only')
    def provider(messages,metrics):
        with SessionLocal.begin() as db: db.add(m.AuditEvent(action='test.connection.database.unlocked'))
        return {'ok':True}
    monkeypatch.setattr('app.routes_extensions.completion',provider)
    assert checked(admin,'/ai/connection-test','POST')['connected'] is True
