"""Loaded inside the pinned DeepTutor image; no modification of upstream source.

Each platform user/project/scope maps to an isolated native non-admin account.
Only a 60-second signed exchange is exposed to the private platform network.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field
from deeptutor.api.main import app
from deeptutor.services.auth import AUTH_ENABLED, add_user, create_token, get_user_info, list_users
from deeptutor.multi_user.grants import empty_grant, save_grant
from deeptutor.multi_user.model_access import admin_catalog, is_owner_bound

_lock = threading.Lock()


class Assertion(BaseModel):
    principal: str = Field(min_length=1, max_length=200)
    expires: int
    audience: str


@app.post('/internal/exchange')
def exchange(data: Assertion, x_zhixing_signature: str = Header(default='')):
    secret = os.environ.get('DEEPTUTOR_BRIDGE_SECRET', '')
    if not AUTH_ENABLED or len(secret) < 32:
        raise HTTPException(503, 'Bridge requires authentication and a 32-character secret')
    body = json.dumps(data.model_dump(), sort_keys=True, separators=(',', ':')).encode()
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_zhixing_signature) or data.audience != 'zhixing-deeptutor' or not 0 < data.expires - time.time() <= 65:
        raise HTTPException(403, 'Invalid identity assertion')
    username = 'zx_' + hashlib.sha256(data.principal.encode()).hexdigest()[:40]
    with _lock:
        if not list_users():
            # Native bootstrap promotes the first account. Reserve it for operations.
            add_user('zx_service_admin', secrets.token_urlsafe(48), role='admin')
        user = get_user_info(username)
        if not user:
            add_user(username, secrets.token_urlsafe(48), role='user')
            user = get_user_info(username)
        if user.get('role') != 'user':
            raise HTTPException(503, 'Execution identity must not be admin')
        grant = empty_grant(user['id'])
        llm = admin_catalog().get('services', {}).get('llm', {})
        profile_id, model_id = llm.get('active_profile_id'), llm.get('active_model_id')
        profile = next((p for p in llm.get('profiles', []) if p.get('id') == profile_id), None)
        if not profile or is_owner_bound(profile) or not model_id:
            raise HTTPException(503, 'Configure a shareable active API-key model first')
        grant['models']['llm'] = [{'profile_id': profile_id, 'model_ids': [model_id]}]
        grant.update(enabled_tools=[], mcp_tools=[], cli_apps=[], exec_enabled=False)
        save_grant(user['id'], grant)
        return {'token': create_token(username, role='user', user_id=user['id'])}
