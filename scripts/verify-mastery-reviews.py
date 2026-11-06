"""Exercise the Mastery Path bridge using only the isolated preview container."""
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from uuid import uuid4
import httpx

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
from app.config import settings
from app.v2 import mastery_reviews as reviews, tutor


def wait_for(read, accept, seconds=100):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = read()
        if accept(result):
            return result
        time.sleep(2)
    raise RuntimeError('Native state did not arrive before the deadline')


def main():
    preview = Path(sys.argv[1]).resolve()
    if not preview.is_relative_to(root / '.runtime') or not preview.name.startswith('tutor-native-preview-'):
        raise SystemExit('Use an isolated tutor-native-preview-* directory')
    settings.deeptutor_url = 'http://127.0.0.1:18012'
    settings.deeptutor_bridge_secret = (preview / 'bridge.key').read_text(encoding='utf-8-sig').strip()
    def ready():
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                return client.get(settings.deeptutor_url + '/health/ready').is_success
        except httpx.HTTPError:
            return False

    wait_for(ready, bool, 60)
    owner = 'review-acceptance:' + uuid4().hex
    name = 'zx_' + hashlib.sha256(owner.encode()).hexdigest()[:48]
    source = '实践是认识的来源，也是检验认识真理性的唯一标准。认识通过实践产生，并通过反馈不断修正。'
    assert tutor.knowledge_request(owner, 'create', name, text=source)['state'] in ('indexing', 'ready')
    wait_for(lambda: tutor.knowledge_request(owner, 'status', name), lambda row: row['state'] == 'ready')
    claims = {'scope_id': uuid4().hex, 'attempt_id': uuid4().hex, 'revision': 1,
              'objective_id': uuid4().hex, 'objective': '实践检验认识真理性', 'title': '复习验收讲义',
              'knowledge_base': name, 'timestamp': time.time() - 20 * 86400, 'correct': True}
    path = reviews.evidence_request(owner, **claims)
    assert reviews.evidence_request(owner, **claims) == path

    def queue():
        return asyncio.run(reviews.topic(owner, path))['reviews']

    assert not queue()  # one answer does not clear native mastery
    for offset in (2, 1):
        assert reviews.evidence_request(owner, **{**claims, 'attempt_id': uuid4().hex,
            'timestamp': claims['timestamp'] - offset * 86400}) == path
    first, = queue()
    assert first['due']
    assert reviews.evidence_request(owner, **{**claims, 'revision': 2, 'correct': False}) == path
    assert not queue()
    assert reviews.evidence_request(owner, **claims) == path
    assert not queue()  # a stale retry cannot overwrite the newer evaluation
    assert reviews.evidence_request(owner, **{**claims, 'revision': 3}) == path
    assert queue()[0]['due_at'] == first['due_at']
    session = reviews.session_request(owner, path, 'start', uuid4().hex)
    assert session['state'] != 'idle'
    session = wait_for(lambda: reviews.session_request(owner, path, 'status'),
                       lambda row: row['state'] in ('waiting_input', 'question'), 180)
    assert session['request_id'] and 'expected_answer' not in json.dumps(session)
    def answer_for(question):
        if question and question['options']:
            return question['options'][0]['label']
        return '实践把主观认识与客观现实联系起来，因此实践结果可以检验并修正认识。'

    question = session['question']
    answers = {child['question_id']: answer_for(child) for child in (question or {}).get('questions', [])}
    reviews.session_request(owner, path, 'answer', uuid4().hex, answer_for(question), session['request_id'], answers)
    session = wait_for(lambda: reviews.session_request(owner, path, 'status'),
                       lambda row: row['state'] == 'idle' or (
                           row['state'] in ('question', 'waiting_input') and row['request_id'] != session['request_id']), 180)
    next_queue = queue()
    assert not next_queue or next_queue[0]['due_at'] != first['due_at'], 'Native review did not apply the answer'
    print(json.dumps({'state': session['state'], 'previous_due': first['due_at'],
                      'native_queue': [{'due': row['due'], 'due_at': row['due_at']} for row in next_queue]}))


if __name__ == '__main__':
    main()
