"""Small server-rendered product views over trusted PostgreSQL records."""
import hmac
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote

import sqlalchemy as sa
from fastapi import HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse

from ..evidence import redact
from .browser_auth import BrowserAuth
from .dashboard import e
from .product_theme import CSS
from .schema_v1 import repositories, runs, attempts, sessions, action_requests, decisions, executions, events
from .schema_v2 import approvals


def text(value):
    return e(str(redact(value)))


def block(value):
    return '<details><summary>Inspect stored evidence</summary><pre>' + e(json.dumps(redact(value), indent=2, default=str)) + '</pre></details>'


def badge(value):
    kind = {'PASS': 'good', 'ALLOW': 'good', 'succeeded': 'good', 'completed': 'good',
            'BLOCK': 'bad', 'DENY': 'bad', 'failed': 'bad', 'failed-infrastructure': 'bad',
            'REVIEW_REQUIRED': 'review', 'running': 'active', 'queued': 'active'}.get(str(value), '')
    return '<span class="badge ' + kind + '">' + text(value) + '</span>'


def link(path, label):
    return '<a href="' + e(path, quote=True) + '">' + text(label) + '</a>'


def segment(value):
    return quote(str(value), safe="")


def form(path, csrf, label, extra=""):
    return (f'<form method="post" action="{e(path, quote=True)}"><input type="hidden" name="csrf" value="{e(csrf)}">'
            + extra + f'<button type="submit">{e(label)}</button></form>')


def page(title, body, actor=None, csrf=None, status=200):
    nav = ('<a class="skip" href="#main">Skip to content</a><aside class="sidebar">'
        '<a class="brand" href="/ui"><span class="brand-mark" aria-hidden="true">R</span>RepoShield</a>'
        '<div class="nav-caption">WORKSPACE</div><nav class="nav-links" aria-label="Main navigation">'
        '<a href="/ui"' + (' aria-current="page"' if title == 'Repositories' else '') + '><span class="nav-icon" aria-hidden="true">▦</span> Repositories</a>')
    if actor: nav += '<a href="/ui/settings"><span class="nav-icon" aria-hidden="true">◇</span> Policy and settings</a>'
    nav += ('</nav><div class="sidebar-note"><strong>Deterministic by design</strong>'
        'Policy, dependencies and evidence. Independent of an LLM.</div><div class="sidebar-foot">VERIFICATION + ACTION CONTROL</div></aside>')
    account = ('<div class="identity"><strong>' + text(actor.id) + '</strong><span>' + text(actor.role) + '</span></div>'
               + form('/ui/logout', csrf, 'Sign out')) if actor else '<span class="badge">Operator workspace</span>'
    html = ("<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f'<title>{e(title)} · RepoShield</title><style>{CSS}'
        '</style></head><body>' + nav + '<div class="workspace"><header class="topbar">'
        '<span class="breadcrumb">Workspace / ' + text(title) + '</span><div class="topbar-right">' + account + '</div></header>'
        '<main id="main"><div class="page-heading"><div class="eyebrow">RepoShield workspace</div>'
        f'<h1>{e(title)}</h1></div>' + body + '<footer class="footer"><span>Evidence before confidence.</span>'
        '<span>Stored observations · Exact context · Explicit decisions</span></footer></main></div></body></html>')
    return HTMLResponse(html, status_code=status, headers={
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


def rows(items):
    if not items:
        return '<div class="empty"><strong>No records yet.</strong>Activity will appear here when it is recorded.</div>'
    return '<ul class="record-list">' + ''.join('<li>' + item + '</li>' for item in items) + '</ul><p class=m>Showing up to 100 most recent records.</p>'


def install_ui(app, cfg, store, actions):
    auth = BrowserAuth(store, cfg.ui_config_file)
    app.state.browser_auth = auth

    @app.exception_handler(HTTPException)
    async def safe_error(request, exc):
        if request.url.path == '/ui' or request.url.path.startswith('/ui/'):
            # Only local, predetermined errors are displayed; never upstream response text.
            return page('Request unavailable', '<p role="alert">' + text(exc.detail) + '</p>'
                        + link('/ui', 'Return to repositories or sign in'), status=exc.status_code)
        return await http_exception_handler(request, exc)

    @app.middleware('http')
    async def ui_headers(request, call_next):
        try:
            response = await call_next(request)
        except sa.exc.SQLAlchemyError:
            if not (request.url.path == '/ui' or request.url.path.startswith('/ui/')):
                raise
            response = page('Temporarily unavailable', '<p role="alert">Stored data could not be loaded. Retry shortly.</p>', status=503)
        if request.url.path == '/ui' or request.url.path.startswith('/ui/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def repo_access(repo_id, actor):
        with store.engine.connect() as c:
            row = c.execute(sa.select(repositories).where(repositories.c.id == repo_id,
                repositories.c.tenant_id == actor.tenant_id, repositories.c.id.in_(actor.repository_ids))).mappings().first()
        if row is None:
            raise HTTPException(404, 'Repository not found')
        return row

    def action_access(action_id, actor):
        with store.engine.connect() as c:
            row = c.execute(sa.select(decisions, action_requests.c.payload.label('request'),
                action_requests.c.session_id).join(action_requests).where(decisions.c.id == action_id)).mappings().first()
        if row is None:
            raise HTTPException(404, 'Action not found')
        session = store.get_session(row['session_id'])
        if session is None:
            raise HTTPException(404, 'Session not found')
        repo_access(session['repository_id'], actor)
        if row['request'].get('repository_id') != session['repository_id'] or row['request'].get('tenant_id') != actor.tenant_id:
            raise HTTPException(404, 'Action not found')
        return row

    def reviewable(row, actor):
        patch = row['request'].get('action', {}).get('patch', '')
        return (actor.role in ('administrator', 'reviewer') and row['payload'].get('requested_by') != actor.id
            and row['decision'] == 'REVIEW_REQUIRED' and row['payload'].get('reason') == 'documentation_patch'
            and row['expires_at'] is not None and row['expires_at'] > datetime.now(timezone.utc)
            and bool(patch) and redact(patch) == patch)

    async def csrf_form(request, session, expected):
        if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
            raise HTTPException(415, 'Use the displayed form')
        raw = await request.body()
        if len(raw) > 2048:
            raise HTTPException(413, 'Form too large')
        try:
            data = parse_qs(raw.decode('utf-8'), strict_parsing=True, max_num_fields=4)
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Invalid form') from None
        if set(data) != expected or any(len(v) != 1 for v in data.values()):
            raise HTTPException(400, 'Invalid form')
        if not hmac.compare_digest(data['csrf'][0].encode(), session['csrf'].encode()):
            raise HTTPException(403, 'Form expired or invalid')
        return {k: v[0] for k, v in data.items()}

    @app.get('/', include_in_schema=False)
    def root():
        return RedirectResponse('/ui', status_code=303)

    @app.get('/ui', include_in_schema=False)
    def home(request: Request):
        try:
            _, actor, login = auth.authenticate(request)
        except HTTPException as exc:
            if exc.status_code not in (401, 503):
                raise
            body = ('<div class="hero"><div class="eyebrow">Independent verification. Deliberate control.</div>'
                    '<h2>Move fast.<br>Know what you can trust.</h2><p>Verify code changes and review controlled agent actions. '
                    'Make every decision traceable to policy and evidence.</p>')
            body += ('<a class="primary-link" href="/ui/auth/login">Sign in with GitHub &nbsp; →</a>' if exc.status_code == 401
                     else '<p class=notice>GitHub sign-in is not configured or unavailable. Ask the operator to complete trusted setup.</p>')
            body += ('</div><div class="mode-grid"><section><span class="mode-index">01 / VERIFY CHANGES</span>'
                '<h2>A clear verdict. A visible reason.</h2><p>Trace proposed changes through deterministic policies, dependency analysis and test evidence.</p>'
                '<span class="mode-foot">Traceable verification decisions</span></section>'
                '<section><span class="mode-index">02 / CONTROL ACTIONS</span><h2>Permission before execution.</h2>'
                '<p>Review exact requests, scoped decisions and execution history. Approval is separate from execution.</p>'
                '<span class="mode-foot">ALLOW · DENY · REVIEW_REQUIRED</span></section></div>')
            return page('RepoShield', body)
        with store.engine.connect() as c:
            repos = c.execute(sa.select(repositories.c.id, repositories.c.name).where(
                repositories.c.tenant_id == actor.tenant_id, repositories.c.id.in_(actor.repository_ids))
                .order_by(repositories.c.created_at.desc()).limit(100)).mappings().all()
        body = '<p>Repository access is assigned by your administrator.</p>'
        body += '<div class="metric-grid"><div class="metric"><span>Visible repositories</span><strong>' + str(len(repos)) + '</strong><small>Up to 100 in your scope</small></div>'
        body += '<div class="metric"><span>Your role</span><strong style="font-size:20px">' + text(actor.role) + '</strong><small>Administrator-assigned access</small></div>'
        body += '<div class="metric"><span>Decision basis</span><strong style="font-size:20px">Evidence</strong><small>No LLM required</small></div></div>'
        body += ('<div class="repo-grid">' + ''.join('<article class="repo-card"><span class="repo-label">Repository</span>'
            '<span class="arrow" aria-hidden="true">↗</span><h2>' + link('/ui/repositories/' + segment(r['id']), r['name'])
            + '</h2><p>Verification runs, controlled sessions and trusted policy</p></article>' for r in repos) + '</div>') if repos else rows([])
        return page('Repositories', body, actor, login['csrf'])

    @app.get('/ui/auth/login', include_in_schema=False)
    def login(request: Request):
        config, browser, url = auth.begin(request)
        response = RedirectResponse(url, status_code=303)
        auth.cookie(response, config, browser, 'login', 300)
        return response

    @app.get('/ui/auth/callback', include_in_schema=False)
    def callback(request: Request):
        config, sid = auth.complete(request)
        response = RedirectResponse('/ui', status_code=303)
        auth.cookie(response, config, sid)
        auth.cookie(response, config, '', 'login', 0)
        return response

    @app.post('/ui/logout', include_in_schema=False)
    async def logout(request: Request):
        config, _, login = auth.authenticate(request)
        await csrf_form(request, login, {'csrf'})
        auth.logout(request, config)
        response = RedirectResponse('/ui', status_code=303)
        auth.cookie(response, config, '', age=0)
        return response

    @app.get('/ui/repositories/{repo_id}', include_in_schema=False)
    def repository(repo_id: str, request: Request):
        _, actor, login = auth.authenticate(request)
        repo = repo_access(repo_id, actor)
        with store.engine.connect() as c:
            recent = c.execute(sa.select(attempts.c.id, attempts.c.state, attempts.c.created_at).join(runs)
                .where(runs.c.repository_id == repo_id).order_by(attempts.c.created_at.desc()).limit(100)).mappings().all()
            controlled = c.execute(sa.select(sessions).where(sessions.c.repository_id == repo_id)
                .order_by(sessions.c.created_at.desc()).limit(100)).mappings().all()
        body = '<p>Trusted base: <code>' + text(repo['base_sha']) + '</code> · Policy epoch: ' + text(repo['policy_epoch']) + '</p>'
        body += '<section><h2>VERIFICATION ONLY</h2>' + rows([link('/ui/attempts/' + segment(r['id']), r['id'])
                + badge(r['state']) for r in recent]) + '</section>'
        body += '<section><h2>CONTROLLED SESSION · DEVELOPMENT EXECUTION</h2><p class=notice>Dedicated Linux acceptance is pending. Approval is not execution.</p>'
        body += rows([link('/ui/sessions/' + segment(s['id']), s['id']) + badge(s['state']) for s in controlled]) + '</section>'
        body += link('/ui/repositories/' + segment(repo_id) + '/policy', 'View trusted action policy')
        return page(repo['name'], body, actor, login['csrf'])

    def history(c, predicate):
        entries = c.execute(sa.select(events.c.created_at, events.c.kind, events.c.actor_id, events.c.data)
            .where(predicate).order_by(events.c.id.desc()).limit(100)).mappings().all()
        return '<h2>Audit timeline</h2>' + ('<ol class="timeline">' + ''.join('<li><strong>' + text(x['kind']) + '</strong><time>' + text(x['created_at']) + '</time>' + block(dict(x)) + '</li>' for x in entries) + '</ol>' if entries else '<p>No audit events yet.</p>') + '<p class=m>Most recent 100 events; full history remains in trusted storage.</p>'

    @app.get('/ui/attempts/{attempt_id}', include_in_schema=False)
    def attempt(attempt_id: str, request: Request):
        _, actor, login = auth.authenticate(request)
        item = store.get_attempt(attempt_id)
        if item is None:
            raise HTTPException(404, 'Run attempt not found')
        repo_access(item['repository_id'], actor)
        body = '<p>VERIFICATION ONLY · State: <strong>' + text(item['state']) + '</strong></p>'
        if item['state'] in ('queued', 'running'):
            body += '<p role=status>Verification is in progress. Reload this page to load the latest stored evidence.</p>'
        result = item['result']
        if result:
            body += badge(result.get('verdict', 'Unknown'))
            body += '<p>' + text(result.get('summary', 'Stored verification result')) + '</p>'
            findings = result.get('findings') or []
            relevant = [f for f in findings if isinstance(f, dict) and f.get('result') not in ('PASS', 'NOT_APPLICABLE')]
            if relevant:
                body += '<section><h2>What needs attention</h2>' + rows([
                    badge(f.get('result', 'Unknown')) + '<strong>' + text(f.get('rule_id', 'Finding'))
                    + '</strong><span>' + text(f.get('message', '')) + '</span>' for f in relevant]) + '</section>'
            body += '<h2>Stored result</h2>' + block({k: result.get(k) for k in ('verdict', 'findings', 'plan', 'execution_availability')})
        else:
            body += '<p class=notice>No verification result is available. Missing evidence is not PASS.</p>'
        order = {'snapshot': 0, 'analyze': 1, 'tests': 2, 'aggregate': 3, 'publish': 4}
        body += '<h2>Stages</h2><div class="stages">' + ''.join('<div class="stage"><strong>' + text(t['stage']) + '</strong>' + badge(t['state']) + '<br><small>Attempts: ' + text(t['tries']) + '</small></div>' for t in sorted(item['tasks'], key=lambda t: order.get(t['stage'], 5))) + '</div>'
        with store.engine.connect() as c:
            inputs = c.scalar(sa.select(runs.c.inputs).where(runs.c.id == item['run_id']))
            body += '<h2>Input identity</h2>' + block({k: inputs.get(k) for k in ('base_sha', 'head_sha', 'policy_epoch', 'implementation_digest', 'profile')})
            body += history(c, events.c.attempt_id == attempt_id)
        return page('Run ' + attempt_id, body, actor, login['csrf'])

    @app.get('/ui/sessions/{session_id}', include_in_schema=False)
    def session_view(session_id: str, request: Request):
        _, actor, login = auth.authenticate(request)
        item = store.get_session(session_id)
        if item is None:
            raise HTTPException(404, 'Session not found')
        repo_access(item['repository_id'], actor)
        body = '<p class=notice>CONTROLLED SESSION · DEVELOPMENT EXECUTION. Dedicated Linux validation pending.</p>'
        body += block({k: item[k] for k in ('owner_id', 'state', 'expires_at', 'unexpired', 'revocation_epoch')})
        with store.engine.connect() as c:
            found = c.execute(sa.select(decisions.c.id, decisions.c.decision).join(action_requests)
                .where(action_requests.c.session_id == session_id).order_by(decisions.c.created_at.desc()).limit(100)).mappings().all()
            body += '<h2>Actions</h2>' + rows([link('/ui/actions/' + segment(r['id']), r['id']) + ' · ' + text(r['decision']) for r in found])
            body += history(c, events.c.session_id == session_id)
        if actor.role == 'administrator' and item['state'] == 'active':
            body += form('/ui/sessions/' + segment(session_id) + '/revoke', login['csrf'], 'Revoke session')
        return page('Session ' + session_id, body, actor, login['csrf'])

    @app.post('/ui/sessions/{session_id}/revoke', include_in_schema=False)
    async def revoke(session_id: str, request: Request):
        _, actor, login = auth.authenticate(request)
        await csrf_form(request, login, {'csrf'})
        if actor.role != 'administrator':
            raise HTTPException(403, 'Administrator role required')
        item = store.get_session(session_id)
        if item is None:
            raise HTTPException(404, 'Session not found')
        repo_access(item['repository_id'], actor)
        store.revoke_session(session_id, actor.id)
        return RedirectResponse('/ui/sessions/' + segment(session_id), status_code=303)

    @app.get('/ui/actions/{action_id}', include_in_schema=False)
    def action_view(action_id: str, request: Request):
        _, actor, login = auth.authenticate(request)
        row = action_access(action_id, actor)
        body = '<h2>Immutable decision and reason</h2>' + block(row['payload'])
        body += '<h2>Exact request identity</h2>' + block(row['request'])
        patch = row['request'].get('action', {}).get('patch')
        if patch and redact(patch) == patch:
            body += '<h2>Requested documentation patch</h2><pre>' + e(patch) + '</pre>'
        with store.engine.connect() as c:
            approved = c.execute(sa.select(approvals).where(approvals.c.decision_id == action_id)).mappings().first()
            execution = c.execute(sa.select(executions.c.id, executions.c.state, executions.c.created_at).where(executions.c.decision_id == action_id)).mappings().first()
        body += '<h2>Separate human approval</h2>' + (block(dict(approved)) if approved else '<p>No approval recorded.</p>')
        body += '<h2>Execution state</h2>' + (block(dict(execution)) if execution else '<p>Not claimed for execution.</p>')
        body += '<p class=notice>Approval does not change the raw decision or run the action. The broker must validate a current, single-use authorization.</p>'
        if not approved and reviewable(row, actor):
            body += form('/ui/actions/' + segment(action_id) + '/approve', login['csrf'], 'Approve this exact request',
                '<input type="hidden" name="digest" value="' + e(row['payload']['action_digest']) + '">')
        else:
            body += '<p>This request is not eligible for approval here (role, self-review, decision, expiry, existing approval, or incomplete/redacted patch).</p>'
        body += link('/ui/sessions/' + segment(row['session_id']), 'Session and audit timeline')
        return page('Action ' + action_id, body, actor, login['csrf'])

    @app.post('/ui/actions/{action_id}/approve', include_in_schema=False)
    async def approve(action_id: str, request: Request):
        _, actor, login = auth.authenticate(request)
        data = await csrf_form(request, login, {'csrf', 'digest'})
        row = action_access(action_id, actor)
        if not reviewable(row, actor):
            raise HTTPException(403, 'This exact request is not eligible for approval')
        if not hmac.compare_digest(data['digest'].encode(), row['payload']['action_digest'].encode()):
            raise HTTPException(409, 'Request identity changed; review the request again')
        # Service revalidates expiry, scope, snapshot, revocation and policy transactionally.
        actions.approve(action_id, actor)
        return RedirectResponse('/ui/actions/' + segment(action_id), status_code=303)

    @app.get('/ui/repositories/{repo_id}/policy', include_in_schema=False)
    def policy(repo_id: str, request: Request):
        _, actor, login = auth.authenticate(request)
        repo_access(repo_id, actor)
        resource = actions.resource(repo_id) if cfg.action_policy_file else None
        body = '<p>Read-only trusted configuration. Changes require an operator outside agent execution.</p>'
        if resource:
            data = resource.model_dump(mode='json')
            body += block({k: data[k] for k in ('resource_id', 'workspace_revision', 'policy_epoch', 'administrator', 'repository', 'execution_profiles', 'default_profile')})
        else:
            body += '<p class=notice>No trusted action policy configured. Actions cannot be authorized.</p>'
        return page('Action policy', body, actor, login['csrf'])

    @app.get('/ui/settings', include_in_schema=False)
    def settings(request: Request):
        config, actor, login = auth.authenticate(request)
        body = '<p>Organization: ' + text(config.organization) + '</p><p>Read-only settings. Contact the operator to change grants.</p>'
        body += '<ul><li>Verification: static worker; required dynamic evidence remains NOT_RUN.</li><li>Actions: separate broker; dedicated Linux acceptance pending.</li><li>GitHub enforcement: live acceptance pending.</li><li>Login: 15-minute session; restart or configuration change signs everyone out.</li></ul>'
        return page('Policy and settings', body, actor, login['csrf'])
