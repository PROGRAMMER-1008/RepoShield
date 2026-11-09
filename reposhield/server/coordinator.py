"""Authenticated PostgreSQL API. Never starts workers or executes repository code."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import sqlalchemy as sa
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..contracts import ActionRequest
from ..authorization import SignedAuthorization, ExecutionProfile, load_public_keys
from .durable import DurableStore
from .identities import authenticate, load_identities, ExecutorIdentity
from .action_service import ActionService
from .authorization_service import IssuanceService, ClaimService
from .execution_service import ExecutionService
from .evidence_service import EvidenceService
from .schema_v1 import repositories, runs, attempts, decisions, action_requests
from .schema_v2 import approvals


class SubmitRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    rerun: bool = Field(default=False, strict=True)
    request_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")

    @model_validator(mode="after")
    def explicit_rerun_key(self):
        if self.rerun != (self.request_key is not None) or self.request_key == "initial":
            raise ValueError("Explicit reruns require a unique request_key; ordinary requests omit it")
        return self


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_id: str = Field(min_length=1, max_length=64)
    ttl_seconds: int = Field(default=3600, strict=True, ge=1, le=3600)


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorization: SignedAuthorization
    request: ActionRequest
    resource_id: str = Field(min_length=1, max_length=64)
    profile: ExecutionProfile


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str
    outcome: dict


def create_coordinator(cfg):
    identities = load_identities(cfg.identities_file)
    store = DurableStore(cfg.database_url)
    store.check_schema()
    actions = ActionService(store, cfg.action_policy_file)
    issuer = IssuanceService(actions, cfg.signing_key_file, cfg.signing_key_id)
    lifecycle = ExecutionService(actions)
    evidence = EvidenceService(store, cfg)
    github = None
    if cfg.github_app_config_file:
        from .github_service import GitHubService
        github = GitHubService(store, cfg)
    if cfg.executor_identities_file:
        with store.engine.connect() as c:
            roots = c.scalars(sa.select(repositories.c.path)).all()
        roots.append(str(Path(__file__).resolve().parents[2]))
        path = Path(cfg.executor_identities_file).resolve(strict=True)
        if any(path.is_relative_to(Path(root).resolve()) for root in roots):
            raise ValueError("executor identity configuration must be outside workspaces")
        executors = load_identities(path, ExecutorIdentity)
    else:
        executors = ()
    if {i.token_sha256 for i in identities} & {i.token_sha256 for i in executors}:
        raise ValueError("executor credentials must be distinct from user/agent credentials")

    @asynccontextmanager
    async def lifespan(_):
        yield
        store.engine.dispose()

    app = FastAPI(title="RepoShield coordinator", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.store = store

    @app.middleware("http")
    async def bounded_request(request, call_next):
        if request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 1048576:
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"detail": "request too large"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def auth(request: Request):
        header = request.headers.get("authorization", "")
        identity = authenticate(identities, header[7:]) if header.startswith("Bearer ") else None
        if identity is None:
            raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Bearer"})
        return identity

    def repository_access(repository_id, actor):
        repo = store.repository(repository_id)
        if (repo is None or repo["tenant_id"] != actor.tenant_id or
                repository_id not in actor.repository_ids):
            raise HTTPException(404, "repository not found")
        return repo

    def executor_auth(request: Request):
        header = request.headers.get("authorization", "")
        actor = authenticate(executors, header[7:]) if header.startswith("Bearer ") else None
        if actor is None:
            raise HTTPException(401, "executor authentication required")
        return actor

    def session_access(session_id, actor, active=False):
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(404, "session not found")
        repository_access(session["repository_id"], actor)
        if session["owner_id"] != actor.id and actor.role != "administrator":
            raise HTTPException(403, "session belongs to another identity")
        if active and (session["state"] != "active" or not session["unexpired"]):
            raise HTTPException(403, "session is revoked or expired")
        return session

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "mode": "VERIFICATION ONLY", "execution_enabled": False}

    @app.get("/api/v1/repositories")
    def list_repositories(actor=Depends(auth)):
        with store.engine.connect() as c:
            return [dict(r) for r in c.execute(sa.select(repositories.c.id, repositories.c.name,
                repositories.c.base_sha, repositories.c.policy_epoch).where(
                repositories.c.tenant_id == actor.tenant_id, repositories.c.id.in_(actor.repository_ids))).mappings()]

    @app.post("/api/v1/repositories/{repository_id}/runs", status_code=202)
    def submit(repository_id: str, body: SubmitRun, actor=Depends(auth)):
        repository_access(repository_id, actor)
        if actor.role == "viewer":
            raise HTTPException(403, "viewer cannot submit verification")
        return store.enqueue(repository_id, body.head_sha, actor.id, rerun_key=body.request_key)

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str, actor=Depends(auth)):
        with store.engine.connect() as c:
            run = c.execute(sa.select(runs).where(runs.c.id == run_id)).mappings().first()
            if run is None:
                raise HTTPException(404, "run not found")
            repository_access(run["repository_id"], actor)
            return {"run": dict(run), "attempts": [dict(r) for r in c.execute(sa.select(attempts.c.id,
                attempts.c.state, attempts.c.created_at).where(attempts.c.run_id == run_id)
                .order_by(attempts.c.created_at)).mappings()]}

    def accessible_attempt(attempt_id, actor):
        attempt = store.get_attempt(attempt_id)
        if attempt is None:
            raise HTTPException(404, "attempt not found")
        repository_access(attempt["repository_id"], actor)
        return attempt

    @app.get("/api/v1/attempts/{attempt_id}")
    def get_attempt(attempt_id: str, actor=Depends(auth)):
        return accessible_attempt(attempt_id, actor)

    @app.get("/api/v1/attempts/{attempt_id}/events")
    def get_events(attempt_id: str, actor=Depends(auth)):
        accessible_attempt(attempt_id, actor)
        return store.attempt_events(attempt_id)

    @app.post("/api/v1/sessions", status_code=201)
    def create_session(body: CreateSession, actor=Depends(auth)):
        repository_access(body.repository_id, actor)
        if actor.role == "viewer":
            raise HTTPException(403, "viewer cannot create sessions")
        scope = actions.scope_for(body.repository_id, actor.id) if cfg.action_policy_file else None
        return {"id": store.create_session(body.repository_id, actor.id, body.ttl_seconds, scope),
                "execution_enabled": False}

    @app.get("/api/v1/sessions/{session_id}")
    def get_session(session_id: str, actor=Depends(auth)):
        return session_access(session_id, actor)

    @app.post("/api/v1/sessions/{session_id}/revoke")
    def revoke(session_id: str, actor=Depends(auth)):
        session_access(session_id, actor)
        store.revoke_session(session_id, actor.id)
        return {"state": "revoked"}

    @app.post("/api/v1/actions/authorize")
    def authorize(body: ActionRequest, actor=Depends(auth)):
        session = session_access(body.session_id, actor, active=True)
        if body.tenant_id != actor.tenant_id or body.repository_id != session["repository_id"]:
            raise HTTPException(403, "action context does not match session")
        if actor.role == "viewer":
            raise HTTPException(403, "viewer cannot request actions")
        return actions.authorize(body, actor)

    @app.post("/api/v1/actions/{action_id}/approve")
    def approve(action_id: str, actor=Depends(auth)):
        if actor.role not in ("administrator", "reviewer"):
            raise HTTPException(403, "reviewer role required; agents cannot approve actions")
        if not cfg.action_policy_file:
            raise HTTPException(501, "trusted action policy is not configured")
        return actions.approve(action_id, actor)

    @app.get("/api/v1/actions/{action_id}")
    def get_action(action_id: str, actor=Depends(auth)):
        with store.engine.connect() as c:
            row = c.execute(sa.select(decisions, action_requests.c.payload.label("request"))
                .join(action_requests).where(decisions.c.id == action_id)).mappings().first()
            if row is None:
                raise HTTPException(404, "decision not found")
            repository_access(row["request"]["repository_id"], actor)
            if actor.role == "agent" and row["payload"]["requested_by"] != actor.id:
                raise HTTPException(403, "action belongs to another identity")
            approval = c.execute(sa.select(approvals).where(approvals.c.decision_id == action_id)).mappings().first()
            return {"decision": row["payload"], "request": row["request"],
                    "approval": dict(approval) if approval else None, "execution_enabled": False}

    @app.post("/api/v1/actions/execute")
    def execute(actor=Depends(auth)):
        raise HTTPException(501, "restricted broker is not enabled until RS2 06")

    @app.post("/api/v1/actions/{action_id}/token")
    def issue_token(action_id: str, actor=Depends(auth)):
        return issuer.issue(action_id, actor)

    @app.post("/api/v1/actions/claim")
    def claim(body: ClaimRequest, executor=Depends(executor_auth)):
        if not cfg.verification_keys_file:
            raise HTTPException(501, "verification keys are not configured")
        try:
            with store.engine.connect() as c:
                roots = c.scalars(sa.select(repositories.c.path)).all()
            roots.append(str(Path(__file__).resolve().parents[2]))
            keys = load_public_keys(cfg.verification_keys_file, roots)
        except (OSError, ValueError, TypeError):
            raise HTTPException(503, "verification keys unavailable or invalid") from None
        return ClaimService(actions, keys).claim(body.authorization, body.request,
                                               body.resource_id, body.profile, executor)

    @app.get("/api/v1/executions/{execution_id}/status")
    def execution_status(execution_id: str, executor=Depends(executor_auth)):
        return lifecycle.status(execution_id, executor)

    @app.post("/api/v1/executions/{execution_id}/result")
    def execution_result(execution_id: str, body: ExecutionResult, executor=Depends(executor_auth)):
        return lifecycle.finish(execution_id, executor, body.state, body.outcome)

    @app.post("/api/v1/evidence/{kind}/{subject_id}/seal")
    def seal_evidence(kind: str, subject_id: str, actor=Depends(auth)):
        return evidence.seal(kind, subject_id, actor)

    @app.get("/api/v1/evidence/{checkpoint_id}")
    def replay_evidence(checkpoint_id: str, actor=Depends(auth)):
        return evidence.replay(checkpoint_id, actor)

    @app.post("/api/v1/evidence/{checkpoint_id}/verify")
    def verify_evidence(checkpoint_id: str, body: dict, actor=Depends(auth)):
        return evidence.replay(checkpoint_id, actor, body)

    @app.post("/api/v1/evidence/{checkpoint_id}/cache-eligibility")
    def cache_eligibility(checkpoint_id: str, body: dict, actor=Depends(auth)):
        return evidence.cache_eligibility(checkpoint_id, actor, body)

    @app.post("/api/v1/github/webhook", status_code=202)
    async def github_webhook(request: Request):
        if github is None: raise HTTPException(503, "GitHub App is not configured")
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(github.receive, request.headers.get("x-github-delivery"),
            request.headers.get("x-github-event", ""), request.headers.get("x-hub-signature-256"), await request.body())

    from .product_ui import install_ui
    install_ui(app, cfg, store, actions)
    return app
