"""Real PostgreSQL/UI requests; GitHub HTTP is explicitly simulated, not live acceptance."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest
import sqlalchemy as sa

from reposhield.server.app import create_app
from reposhield.server.config import ServerConfig
from reposhield.server.browser_auth import BrowserConfig, BrowserAuth
from reposhield.server.schema_v1 import repositories, decisions, executions
from reposhield.server.schema_v2 import approvals
from reposhield.server.process_worker import ProcessWorker
from tests.test_durable import pg, registered, enqueue
from tests.test_action_policy import service, request, patch, actor


@pytest.fixture
def ui(service, pg, tmp_path):
    svc, sid, policy = service
    identities = tmp_path / 'identities.json'
    identities.write_text(json.dumps([dict(id='api-agent', tenant_id='tenant', role='agent', repository_ids=['repo'], token_sha256=hashlib.sha256(b'api-only').hexdigest())]))
    with tempfile.TemporaryDirectory(prefix='rs-ui-trusted-') as trusted:
        folder = Path(trusted)
        secret = folder / 'oauth-secret.txt'
        secret.write_text('fake-oauth-client-secret-not-live')
        path = folder / 'ui.json'
        config = dict(client_id='fake-client', client_secret_file=str(secret), origin='https://reposhield.test',
            organization='synthetic-org', organization_id=99, tenant_id='tenant', members=[
                dict(github_id=i, id=name, role=role, repository_ids=['repo']) for i, name, role in
                [(1, 'admin', 'administrator'), (2, 'reviewer', 'reviewer'), (3, 'viewer', 'viewer')]])
        path.write_text(json.dumps(config))
        cfg = ServerConfig(database_url=pg[1], identities_file=str(identities), action_policy_file=str(policy), ui_config_file=str(path))
        app = create_app(cfg)
        state = dict(user=2, membership='active', org=99, status=200, calls=[])
        def transport(method, url, headers, body):
            state['calls'].append((method, url))
            if url.endswith('/access_token'):
                data = json.loads(body)
                assert data['client_secret'] == secret.read_text()
                assert data['redirect_uri'] == config['origin'] + '/ui/auth/callback'
                challenge = base64.urlsafe_b64encode(hashlib.sha256(data['code_verifier'].encode()).digest()).rstrip(b'=').decode()
                assert challenge == state['challenge']
                return state['status'], dict(access_token='fake-upstream-access-token', token_type='bearer')
            assert headers['Authorization'] == 'Bearer fake-upstream-access-token'
            if url.endswith('/user'):
                return state['status'], dict(id=state['user'], login='ignored-user-name')
            assert url.endswith('/user/memberships/orgs/synthetic-org')
            return state['status'], dict(state=state['membership'], organization=dict(id=state['org']), user=dict(id=state['user']))
        app.state.browser_auth.transport = transport
        with TestClient(app, base_url=config['origin'], follow_redirects=False) as client:
            def begin():
                response = client.get('/ui/auth/login')
                assert response.status_code == 303
                q = parse_qs(urlsplit(response.headers['location']).query)
                assert q['scope'] == ['read:org'] and q['code_challenge_method'] == ['S256']
                state['challenge'] = q['code_challenge'][0]
                return q['state'][0]
            def signin(user=2):
                state['user'] = user
                nonce = begin()
                response = client.get('/ui/auth/callback', params=dict(state=nonce, code='fake-code'))
                assert response.status_code == 303, response.text
                return response
            yield dict(client=client, app=app, auth=app.state.browser_auth, signin=signin, begin=begin,
                config=config, path=path, state=state, store=svc.store, svc=svc, sid=sid, policy=policy)


def csrf(response):
    return re.search(r'name="csrf" value="([^"]+)"', response.text)[1]


def post(ui, url, response, **fields):
    return ui['client'].post(url, data=dict(csrf=csrf(response), **fields), headers={'origin': ui['config']['origin']})


def preview(name, response):
    folder = os.environ.get('REPOSHIELD_TEST_UI_PREVIEW_DIR')
    if folder:
        output = Path(folder)
        output.mkdir(parents=True, exist_ok=True)
        # Visual inspection only; never retain a reusable CSRF value in artifacts.
        sanitized = re.sub(r'name="csrf" value="[^"]+"', 'name="csrf" value="REMOVED"', response.text)
        (output / (name + '.html')).write_text(sanitized, encoding='utf-8')


def test_oauth_cookie_pkce_logout_and_machine_api_separation(ui):
    c = ui['client']
    assert 'Sign in with GitHub' in c.get('/ui').text
    result = ui['signin']()
    cookies = result.headers.get_list('set-cookie')
    assert any('__Host-rs_session=' in x and 'HttpOnly' in x and 'Secure' in x and 'SameSite=lax' in x for x in cookies)
    home = c.get('/ui')
    assert 'demo' in home.text and 'reviewer' in home.text
    assert home.headers['cache-control'] == 'no-store' and home.headers['referrer-policy'] == 'no-referrer'
    assert "frame-ancestors 'none'" in home.headers['content-security-policy']
    assert c.get('/api/v1/repositories').status_code == 401
    assert 'fake-upstream-access-token' not in home.text and 'localStorage' not in home.text
    assert post(ui, '/ui/logout', home).status_code == 303
    assert c.get('/ui/settings').status_code == 401


@pytest.mark.parametrize('field,value', [('user', 999), ('membership', 'pending'), ('org', 98), ('status', 403)])
def test_oauth_unknown_nonmember_wrong_org_and_remote_failure_fail_closed(ui, field, value):
    state = ui['begin']()
    ui['state'][field] = value
    response = ui['client'].get('/ui/auth/callback', params=dict(state=state, code='sensitive-code'))
    assert response.status_code == 403
    assert 'sensitive-code' not in response.text and 'fake-upstream' not in response.text
    assert not ui['auth'].sessions


@pytest.mark.parametrize('fault', ['wrong-state', 'missing-cookie', 'expired', 'duplicate-code'])
def test_oauth_state_browser_binding_expiry_and_duplicate_parameters(ui, fault):
    nonce = ui['begin']()
    if fault == 'missing-cookie': ui['client'].cookies.clear()
    if fault == 'expired': ui['auth'].clock = lambda: 10**15
    if fault == 'wrong-state': nonce = 'wrong-state'
    params = [('state', nonce), ('code', 'fake-code')]
    if fault == 'duplicate-code': params.append(('code', 'other-code'))
    assert ui['client'].get('/ui/auth/callback', params=params).status_code in (400, 403)
    assert ui['state']['calls'] == [] and not ui['auth'].sessions


def test_oauth_callback_is_single_use_and_session_expires(ui):
    nonce = ui['begin']()
    params = dict(state=nonce, code='fake-code')
    assert ui['client'].get('/ui/auth/callback', params=params).status_code == 303
    count = len(ui['state']['calls'])
    assert ui['client'].get('/ui/auth/callback', params=params).status_code == 403
    assert len(ui['state']['calls']) == count
    ui['auth'].clock = lambda: 10**15
    assert ui['client'].get('/ui/settings').status_code == 401


def test_configuration_change_revokes_browser_session(ui):
    ui['signin']()
    ui['config']['members'][1]['role'] = 'viewer'
    ui['path'].write_text(json.dumps(ui['config']))
    assert ui['client'].get('/ui/settings').status_code == 401
    ui['signin']()
    assert 'viewer' in ui['client'].get('/ui/settings').text


@pytest.mark.parametrize('origin,allowed', [('http://public.example', False), ('http://127.0.0.1:8080', False), ('https://user:pass@example.test', False), ('https://example.test/path', False), ('https://example.test?x=1', False), ('https://example.test', True)])
def test_origin_configuration_boundary(ui, origin, allowed):
    config = {**ui['config'], 'origin': origin}
    if allowed:
        assert BrowserConfig.model_validate(config)
    else:
        with pytest.raises(ValueError): BrowserConfig.model_validate(config)
    if origin == 'http://127.0.0.1:8080':
        assert BrowserConfig.model_validate({**config, 'allow_loopback_http': True})


@pytest.mark.parametrize('boundary', ['repository', 'installation'])
def test_external_config_boundary_and_no_bearer_ui_login(ui, demo_repo, boundary):
    import reposhield.server.browser_auth as browser_auth
    # Exercise actual protected roots, independent of checkout/installed-wheel layout.
    root = Path(demo_repo) if boundary == 'repository' else Path(browser_auth.__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix='rs-ui-forbidden-', dir=root) as directory:
        path = Path(directory) / 'bad-ui.json'
        path.write_text(json.dumps(ui['config']))
        with pytest.raises(Exception) as exc:
            BrowserAuth(ui['store'], str(path))
        assert getattr(exc.value, 'status_code', None) == 503
    assert ui['client'].get('/ui/settings', headers={'Authorization': 'Bearer api-only'}).status_code == 401


def test_real_worker_views_and_loading_empty_states(ui, demo_repo):
    ui['signin']()
    c = ui['client']
    assert 'No records yet' in c.get('/ui/repositories/repo').text
    job = enqueue(ui['store'], demo_repo)
    path = '/ui/attempts/' + job['attempt_id']
    waiting = c.get(path)
    assert waiting.status_code == 200 and 'in progress' in waiting.text and 'Missing evidence is not PASS' in waiting.text
    worker = ProcessWorker(ui['store'], 'ui-test')
    while worker.run_once(): pass
    result = c.get(path)
    assert result.status_code == 200 and 'PASS' in result.text and 'TASK_COMPLETED' in result.text
    assert 'trusted-policy.json' not in result.text
    preview('verification', result)
    preview('repositories', c.get('/ui/repositories/repo'))
    assert c.get('/ui/repositories/repo/policy').status_code == 200


def test_exact_approval_keeps_decision_separate_and_displays_execution_audit(ui):
    decision = ui['svc'].authorize(request(patch('docs/guide.md'), ui['sid']), actor())
    ui['signin']()
    path = '/ui/actions/' + decision['id']
    view = ui['client'].get(path)
    assert 'documentation_patch' in view.text and '+new' in view.text and 'Approve this exact request' in view.text
    assert post(ui, path + '/approve', view, digest='0'*64).status_code == 409
    assert post(ui, path + '/approve', view, digest=decision['action_digest']).status_code == 303
    with ui['store'].engine.begin() as c:
        assert c.scalar(sa.select(decisions.c.decision).where(decisions.c.id == decision['id'])) == 'REVIEW_REQUIRED'
        assert c.scalar(sa.select(approvals.c.actor_id).where(approvals.c.decision_id == decision['id'])) == 'reviewer'
        c.execute(executions.insert().values(id='recorded-unknown', decision_id=decision['id'], state='unknown-outcome', outcome={'stdout': 'NEVER_RENDER_PROCESS_LOG'}))
    view = ui['client'].get(path)
    assert 'unknown-outcome' in view.text and 'NEVER_RENDER_PROCESS_LOG' not in view.text
    assert 'ACTION_APPROVED' in ui['client'].get('/ui/sessions/' + ui['sid']).text
    preview('action', view)
    preview('session', ui['client'].get('/ui/sessions/' + ui['sid']))


@pytest.mark.parametrize('fault', ['viewer', 'self', 'deny', 'revoked', 'policy', 'redacted'])
def test_approval_cannot_bypass_existing_authority(ui, fault):
    sid, who = ui['sid'], actor()
    if fault == 'self':
        who = actor('reviewer')
        sid = ui['store'].create_session('repo', 'reviewer', action_scope=ui['svc'].scope_for('repo', 'reviewer'))
    action = patch('docs/guide.md')
    if fault == 'deny': action = {'action_type': 'DATABASE_OPERATION', 'resource_id': 'production'}
    if fault == 'redacted': action['patch'] = action['patch'].replace('+new', '+password=secretvalue')
    decision = ui['svc'].authorize(request(action, sid), who)
    ui['signin'](3 if fault == 'viewer' else 2)
    path = '/ui/actions/' + decision['id']
    view = ui['client'].get(path)
    if fault == 'revoked': ui['store'].revoke_session(sid, 'admin')
    if fault == 'policy':
        with ui['store'].engine.begin() as c: c.execute(repositories.update().values(policy_epoch=2))
    assert post(ui, path + '/approve', view, digest=decision['action_digest']).status_code in (403, 409)
    with ui['store'].engine.connect() as c: assert c.scalar(sa.select(sa.func.count()).select_from(approvals)) == 0
    assert 'secretvalue' not in view.text


def test_csrf_origin_and_admin_only_revocation(ui):
    ui['signin']()
    c = ui['client']
    view = c.get('/ui/sessions/' + ui['sid'])
    url = '/ui/sessions/' + ui['sid'] + '/revoke'
    assert c.post(url, data={'csrf': csrf(view)}).status_code == 403
    assert c.post(url, data={'csrf': csrf(view)}, headers={'origin': 'https://evil.test'}).status_code == 403
    assert c.post(url, data={'csrf': 'wrong'}, headers={'origin': ui['config']['origin']}).status_code == 403
    assert post(ui, url, view).status_code == 403
    assert ui['store'].get_session(ui['sid'])['state'] == 'active'
    ui['signin'](1)
    assert post(ui, url, c.get('/ui/sessions/' + ui['sid'])).status_code == 303
    assert ui['store'].get_session(ui['sid'])['state'] == 'revoked'


def test_cross_tenant_and_repository_object_ids_are_denied(ui, demo_repo):
    decision = ui['svc'].authorize(request(patch('docs/guide.md'), ui['sid']), actor())
    job = enqueue(ui['store'], demo_repo)
    # A valid signed-in user with no grant to repo cannot gain access by changing a URL.
    ui['config']['members'][1]['repository_ids'] = ['other']
    ui['path'].write_text(json.dumps(ui['config']))
    ui['signin']()
    c = ui['client']
    home = c.get('/ui')
    for path in ['/ui/repositories/repo', '/ui/repositories/repo/policy', '/ui/attempts/'+job['attempt_id'], '/ui/sessions/'+ui['sid'], '/ui/actions/'+decision['id']]:
        assert c.get(path).status_code == 404
    assert post(ui, '/ui/actions/'+decision['id']+'/approve', home, digest=decision['action_digest']).status_code == 404
    ui['config']['members'][1]['repository_ids'] = ['repo']
    ui['config']['tenant_id'] = 'other-tenant'
    ui['path'].write_text(json.dumps(ui['config']))
    ui['signin']()
    assert c.get('/ui/repositories/repo').status_code == 404


def test_untrusted_text_is_escaped_and_storage_error_is_safe(ui, monkeypatch):
    with ui['store'].engine.begin() as c:
        c.execute(repositories.update().values(name='<script>alert(1)</script>'))
    ui['signin']()
    response = ui['client'].get('/ui')
    assert '<script>' not in response.text and '&lt;script&gt;' in response.text
    def fail(*args, **kwargs): raise sa.exc.SQLAlchemyError('password=LEAK_THIS')
    monkeypatch.setattr(ui['app'].state.store.engine, 'connect', fail)
    response = ui['client'].get('/ui/settings')
    assert response.status_code == 503 and 'LEAK_THIS' not in response.text


def test_malformed_csrf_duplicate_fields_and_wrong_host_are_rejected(ui):
    ui['signin']()
    c = ui['client']
    origin = {'origin': ui['config']['origin']}
    assert c.post('/ui/logout', data={'csrf': '\u00e9'}, headers=origin).status_code == 403
    view = c.get('/ui')
    assert c.post('/ui/logout', content='csrf=' + csrf(view) + '&csrf=duplicate',
        headers={**origin, 'content-type': 'application/x-www-form-urlencoded'}).status_code == 400
    assert c.post('/ui/logout', json={'csrf': csrf(view)}, headers=origin).status_code == 415
    assert c.get('/ui/settings', headers={'host': 'evil.test'}).status_code == 400
    assert c.get('/ui/settings').status_code == 200


def test_bounded_login_state_and_restart_revocation(ui):
    ui['signin']()
    auth = ui['auth']
    for i in range(256): auth.pending[str(i)] = {'until': auth.clock() + 300}
    assert ui['client'].get('/ui/auth/login').status_code == 429
    restarted = BrowserAuth(ui['store'], str(ui['path']))
    assert restarted.sessions == {} and restarted.pending == {}
    # No bearer credential or upstream user access token is retained in session state.
    assert 'fake-upstream-access-token' not in repr(auth.sessions)


def test_missing_ui_configuration_is_an_honest_empty_state(ui):
    ui['auth'].path = None
    response = ui['client'].get('/ui')
    assert response.status_code == 200 and 'sign-in is not configured' in response.text
    assert 'PASS' not in response.text
    assert ui['client'].get('/ui/auth/login').status_code == 503


def test_required_tests_stay_review_required_in_real_worker_ui(ui, demo_repo):
    ui['signin']()
    job = enqueue(ui['store'], demo_repo, branch='pr/safe-refactor')
    worker = ProcessWorker(ui['store'], 'ui-required-evidence')
    while worker.run_once(): pass
    response = ui['client'].get('/ui/attempts/' + job['attempt_id'])
    assert response.status_code == 200 and 'REVIEW_REQUIRED' in response.text and 'NOT_RUN' in response.text
    assert ui['store'].get_attempt(job['attempt_id'])['result']['verdict'] == 'REVIEW_REQUIRED'
