import logging
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update, or_, and_
from .db import SessionLocal
from . import models as m
from .content import parse_chunks
from .ai import run_tutor, WorkflowError

logger = logging.getLogger('zhixing.worker')


def tick():
    with SessionLocal.begin() as db:
        now = m.now()
        # Recover leases; cap repeated crashes instead of retrying forever.
        for expired in db.scalars(select(m.Job).where(m.Job.state == 'running', m.Job.lease_until < now)):
            expired.state = 'queued' if expired.attempts < 2 else 'failed'
            expired.error_code = 'WORKER_INTERRUPTED'
            if expired.kind == 'ai_request':
                run = db.get(m.AIRequest, expired.resource_id)
                run.state, run.error_code = expired.state, expired.error_code
        job = db.scalar(select(m.Job).where(m.Job.state == 'queued').order_by(m.Job.created_at))
        job_id = None
        if job:
            changed = db.execute(update(m.Job).where(m.Job.id == job.id, m.Job.state == 'queued').values(state='running', attempts=job.attempts+1,
                lease_until=(datetime.now(timezone.utc)+timedelta(seconds=120)).isoformat()))
            if changed.rowcount:
                job_id = job.id
                if job.kind == 'ai_request':
                    db.get(m.AIRequest, job.resource_id).state = 'running'
        event = db.scalar(select(m.OutboxEvent).where(m.OutboxEvent.state == 'queued').order_by(m.OutboxEvent.created_at))
        if event:
            a = db.get(m.Attempt, event.attempt_id)
            member = db.get(m.Membership, a.membership_id)
            db.add(m.AuditEvent(org_id=member.org_id, actor_id=member.user_id, action='learning.evidence.updated', resource_id=a.id))
            event.state = 'processed'
    if not job_id:
        return False
    try:
        with SessionLocal() as db:
            claimed = db.get(m.Job, job_id)
            kind, resource_id = claimed.kind, claimed.resource_id
        if kind == 'tutor':
            run_tutor(resource_id)
        elif kind == 'ai_request':
            from .ai_services import process_request
            process_request(resource_id)
        elif kind == 'document':
            from .documents import parse_document
            with SessionLocal() as db:
                parse_document(db, resource_id, release_transaction=True)
                db.commit()
        elif kind == 'index':
            from .search import process_index
            process_index(resource_id)
        with SessionLocal.begin() as db:
            job = db.get(m.Job, job_id)
            if job.kind == 'parse':
                version = db.get(m.SourceVersion, job.resource_id)
                parse_chunks(db, version)
                source = db.get(m.Source, version.source_id)
                db.add(m.Job(org_id=source.org_id, owner_id=source.owner_id, kind='index', resource_id=version.id))
            elif job.kind in ('tutor', 'ai_request', 'document', 'index'):
                pass
            else:
                raise WorkflowError('UNKNOWN_JOB')
            job.state, job.error_code, job.lease_until = 'succeeded', '', None
    except Exception as exc:
        from .documents import DocumentError
        from .search import SearchUnavailable
        code = exc.code if isinstance(exc, WorkflowError) else str(exc) if isinstance(exc, (DocumentError, SearchUnavailable)) else 'JOB_FAILED'
        with SessionLocal.begin() as db:
            job = db.get(m.Job, job_id)
            job.state = 'queued' if isinstance(exc, WorkflowError) and exc.retry and job.attempts < 2 else 'failed'
            job.error_code, job.lease_until = code, None
            if job.kind == 'tutor':
                run = db.get(m.WorkflowRun, job.resource_id)
                run.status = job.state
                run.result = {'error_code': code, 'message': 'AI 任务未完成，原始作答已保留；可重试或联系教师。'}
            elif job.kind == 'ai_request':
                run = db.get(m.AIRequest, job.resource_id)
                run.state, run.error_code = job.state, code
            elif job.kind == 'document':
                doc = db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id == job.resource_id))
                doc.state, doc.error_code = 'failed', code
        logger.warning('job=%s error=%s', job_id, code)
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    from .search import encode_segments, SearchUnavailable
    try:
        encode_segments('学习资料检索准备')
    except SearchUnavailable:
        logger.warning('local retrieval unavailable; model setup required')
    while True:
        try:
            if not tick():
                time.sleep(1)
        except KeyboardInterrupt:
            break
        except Exception:
            logger.error('worker tick failed; retrying')
            time.sleep(3)


if __name__ == '__main__':
    main()
