"""Database-only maintenance runs independently of model latency."""
import logging
import time
from sqlalchemy import select
from ..db import SessionLocal
from . import models as m, service as s
from .assessments import close_expired

logger = logging.getLogger('zhixing.v2.maintenance')


def tick():
    with SessionLocal() as db:
        due = list(db.execute(select(m.Assessment.project_id, m.Assessment.id)
            .where(m.Assessment.state == 'active', m.Assessment.deadline_at <= s.clock().isoformat())
            .order_by(m.Assessment.deadline_at).limit(30)))
    for project_id, assessment_id in due:
        try:
            with SessionLocal.begin() as db:
                if close_expired(db, project_id, assessment_id):
                    logger.info('assessment_deadline_closed project=%s assessment=%s', project_id, assessment_id)
        except Exception:
            logger.exception('assessment_deadline_error project=%s assessment=%s', project_id, assessment_id)
    return len(due)


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            tick()
        except Exception:
            logger.exception('maintenance_tick_failed')
        time.sleep(2)
