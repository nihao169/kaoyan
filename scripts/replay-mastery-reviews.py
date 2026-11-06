"""Stage historical evidence and report the native queue before activating it."""
import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import learning, models as old
from app.config import settings
from app.db import SessionLocal
from app.v2 import mastery_reviews as reviews, models as m, tutor_index


def stage():
    counts = Counter()
    with SessionLocal.begin() as db:
        for attempt in db.scalars(select(old.Attempt).where(old.Attempt.submitted_at.is_not(None))
                                  .order_by(old.Attempt.submitted_at, old.Attempt.id)):
            try:
                ctx = reviews.owner_context(db, attempt.membership_id)
            except HTTPException:
                counts['skipped_v1_account'] += 1
                continue
            question = db.get(old.QuestionVersion, attempt.question_version_id)
            evaluation = learning.current_evaluation(db, attempt.id)
            if not question or not evaluation:
                counts['skipped_v1_ungraded'] += 1
            else:
                outcome = reviews.enqueue_v1(db, ctx, attempt, question, evaluation)
                counts[f'{outcome}_v1'] += 1
        for attempt in db.scalars(select(m.Attempt).order_by(m.Attempt.created_at, m.Attempt.id)):
            task = db.get(m.Task, attempt.task_id)
            project = db.get(m.Project, task.project_id)
            question = db.get(m.Question, task.payload.get('question_id')) if task.payload.get('question_id') else None
            if not question or attempt.result.get('evaluator') not in ('rule', 'deeptutor_practice'):
                counts['skipped_v2_unverified'] += 1
            else:
                outcome = reviews.enqueue_v2(db, project, task, question, attempt, attempt.result['correct'])
                counts[f'{outcome}_v2'] += 1
    return counts


async def report():
    counts = Counter()
    bindings = []
    with SessionLocal() as db:
        for event in db.scalars(select(m.MasteryReviewEvent)):
            counts[event.state] += 1
        for scope in db.scalars(select(m.MasteryReviewScope).where(m.MasteryReviewScope.path_id.is_not(None))):
            try:
                principal, _, _ = reviews.scope_access(db, reviews.owner_context(db, scope.membership_id), scope)
            except HTTPException:
                counts['revoked_scopes'] += 1
                continue
            bindings.append((principal, scope.path_id))
    for principal, path_id in bindings:
        try:
            native = await reviews.topic(principal, path_id)
        except reviews.tutor.TutorError:
            counts['unavailable_paths'] += 1
            continue
        counts['paths'] += 1
        counts['review_items'] += len(native['reviews'])
        counts['due_items'] += sum(row['due'] for row in native['reviews'])
        counts['mastered'] += native.get('map', {}).get('counts', {}).get('mastered', 0)
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', action='store_true', help='Explicitly allow staging the release database')
    parser.add_argument('--deliver-seconds', type=int, default=0, help='Run deliveries for up to this many seconds')
    args = parser.parse_args()
    url = make_url(settings.database_url)
    if url.get_backend_name() != 'postgresql' or url.host not in ('127.0.0.1', 'localhost'):
        parser.error('Use a dedicated local PostgreSQL database')
    if args.release:
        if url.database != 'zhixing_v2_release' or settings.deeptutor_url.rstrip('/') != 'http://127.0.0.1:18001':
            parser.error('--release requires the release database and its private DeepTutor port')
    elif (not (url.database or '').startswith('zhixing_tutor_native_')
          or settings.deeptutor_url.rstrip('/') != 'http://127.0.0.1:18012'):
        parser.error('Use an isolated zhixing_tutor_native_* database with the preview DeepTutor port')
    reviews.tutor.require_configuration()
    settings.deeptutor_native_knowledge = True
    staged = stage()
    deadline = time.monotonic() + args.deliver_seconds
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            pending = db.scalar(select(m.MasteryReviewEvent.id).where(m.MasteryReviewEvent.state == 'queued').limit(1))
        if not pending:
            break
        if not (tutor_index.tick() or reviews.tick(replay=True)):
            time.sleep(2)
    print(json.dumps({'staging': staged, 'native': asyncio.run(report())}, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
