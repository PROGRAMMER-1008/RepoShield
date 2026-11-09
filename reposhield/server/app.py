from __future__ import annotations

import base64
from contextlib import asynccontextmanager
import hmac
import json
import os
import re
import secrets
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import __version__
from ..audit import read_events, verify_chain
from ..gitutil import is_git_repo
from . import dashboard as ui
from .config import ServerConfig
from .db import Store
from .github import GitHubClient, parse_pull_request, repo_allowed, verify_signature
from .worker import Worker

REF_OK = re.compile(r"^[A-Za-z0-9_./~^@{}-]{1,200}$")


def _ref(value: str | None, default: str | None) -> str | None:
    v = value or default
    if v is None:
        return None
    if v.startswith("-") or ".." in v or not REF_OK.match(v):
        raise HTTPException(422, f"invalid git ref: {v!r}")
    return v


def create_app(cfg: ServerConfig, start_workers: bool = True, github: GitHubClient | None = None) -> FastAPI:
    if cfg.database_url:
        from .coordinator import create_coordinator
        return create_coordinator(cfg)  # the durable API never starts worker threads
    store = Store(cfg.db_path)
    github = github or GitHubClient(cfg.github_token)
    worker = Worker(cfg, store, github)
    @asynccontextmanager
    async def lifespan(_app):
        if start_workers:
            worker.start()
        yield
        worker.stop()

    app = FastAPI(title="RepoShield", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.cfg, app.state.store, app.state.worker, app.state.github = cfg, store, worker, github
    csrf = secrets.token_hex(16)
    nc = lambda x: os.path.normcase(os.path.realpath(x))          # Windows: C:\\Users vs c:\\users
    roots = [nc(r) for r in cfg.local_roots]

    def auth(request: Request):
        if not cfg.api_token:
            return
        h, tok = request.headers.get("authorization", ""), None
        if h.lower().startswith("bearer "):
            tok = h[7:].strip()
        elif h.lower().startswith("basic "):
            try:
                tok = base64.b64decode(h[6:]).decode().split(":", 1)[1]
            except Exception:
                tok = None
        if not tok or not hmac.compare_digest(tok, cfg.api_token):
            raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": 'Basic realm="reposhield"'})

    def local_repo(path: str) -> str:
        if not roots:
            raise HTTPException(403, "local verification is disabled (start the server with --allow-local ROOT)")
        real = os.path.realpath(path)
        if not any(nc(real) == r or nc(real).startswith(r + os.sep) for r in roots):
            raise HTTPException(403, "repository is outside the allowed local roots")
        if not os.path.isdir(real) or not is_git_repo(real):
            raise HTTPException(422, "not a git repository")
        return real

    def enqueue_local(repo_path, base, head, force):
        real = local_repo(repo_path)
        return store.create_run(source="local", repo=os.path.basename(real), repo_path=real, base=_ref(base, None),
                                head=_ref(head, "HEAD"), meta={"force": bool(force)}, supersede=False)

    def read_result(row):
        if row["status"] != "done" or not row.get("run_dir"):
            return None
        try:
            with open(os.path.join(row["run_dir"], "result.json"), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------------ API
    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": __version__, "queue": store.stats()}

    @app.post("/api/v1/verify", status_code=202, dependencies=[Depends(auth)])
    async def api_verify(request: Request):
        try:
            body = await request.json()
            rid = enqueue_local(body["repo_path"], body.get("base"), body.get("head"), body.get("force"))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "expected JSON: {repo_path, base?, head?, force?}")
        return {"id": rid, "status": "queued"}

    @app.get("/api/v1/runs", dependencies=[Depends(auth)])
    def api_runs(verdict: str | None = None, repo: str | None = None, limit: int = 100):
        return {"runs": store.list(min(max(limit, 1), 500), verdict, repo), "stats": store.stats()}

    @app.get("/api/v1/runs/{rid}", dependencies=[Depends(auth)])
    def api_run(rid: str):
        row = store.get(rid)
        if not row:
            raise HTTPException(404, "unknown run")
        return {"run": row, "result": read_result(row)}

    @app.get("/api/v1/runs/{rid}/report", dependencies=[Depends(auth)])
    def api_report(rid: str):
        row = store.get(rid)
        if not row or row["status"] != "done":
            raise HTTPException(404, "report not available")
        try:
            with open(os.path.join(row["run_dir"], "report.html"), encoding="utf-8") as fh:
                content = fh.read()
        except OSError:
            raise HTTPException(404, "report file missing")
        return HTMLResponse(content, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
                                              "X-Content-Type-Options": "nosniff"})

    @app.get("/api/v1/runs/{rid}/audit", dependencies=[Depends(auth)])
    def api_audit(rid: str):
        row = store.get(rid)
        if not row or not row.get("run_dir"):
            raise HTTPException(404, "audit log not available")
        path = os.path.join(row["run_dir"], "events.jsonl")
        ok, msg = verify_chain(path)
        return {"intact": ok, "message": msg, "events": read_events(path) if ok else []}

    # -------------------------------------------------------------- webhook
    @app.post("/webhooks/github")
    async def webhook(request: Request):
        if not cfg.webhook_secret:
            raise HTTPException(503, "webhook disabled: GITHUB_WEBHOOK_SECRET is not configured")
        raw = await request.body()
        if not verify_signature(cfg.webhook_secret, raw, request.headers.get("x-hub-signature-256")):
            raise HTTPException(401, "invalid signature")
        event = request.headers.get("x-github-event", "")
        if event == "ping":
            return {"ok": True}
        if event != "pull_request":
            return {"ignored": event}
        delivery = request.headers.get("x-github-delivery")
        if delivery and store.seen_delivery(delivery):
            return {"duplicate": True}
        try:
            info = parse_pull_request(json.loads(raw))
        except ValueError:
            raise HTTPException(400, "malformed JSON")
        if info is None:
            return {"ignored": "action or payload not handled"}
        if not repo_allowed(cfg.allowed_repos, info["repo"]):
            raise HTTPException(403, f"repository {info['repo']} is not on the allow-list")
        rid = store.create_run(source="github", repo=info["repo"], base=info["base_ref"], head=info["head_sha"],
                               pr_number=info["pr_number"], meta=info)
        target = f"{cfg.public_url.rstrip('/')}/runs/{rid}" if cfg.public_url else None
        await run_in_threadpool(lambda: worker._safe(github.set_status, info["repo"], info["head_sha"], "pending",
                                                     "RepoShield is verifying this change", target))
        return JSONResponse({"id": rid, "status": "queued"}, status_code=202)

    # ------------------------------------------------------------ dashboard
    sec = {"Content-Security-Policy": ui.CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def index(verdict: str | None = None, repo: str | None = None):
        return HTMLResponse(ui.dashboard(store.stats(), store.list(100, verdict, repo), csrf, bool(roots), __version__,
                                         {"verdict": verdict, "repo": repo}), headers=sec)

    @app.get("/runs/{rid}", response_class=HTMLResponse, dependencies=[Depends(auth)])
    def run_view(rid: str):
        row = store.get(rid)
        if not row:
            raise HTTPException(404, "unknown run")
        chain = verify_chain(os.path.join(row["run_dir"], "events.jsonl")) if row.get("run_dir") else None
        return HTMLResponse(ui.run_page(row, read_result(row), chain), headers=sec)

    @app.post("/ui/verify", dependencies=[Depends(auth)])
    async def ui_verify(request: Request):
        raw = await request.body()
        if len(raw) > 8192:
            raise HTTPException(413, "form too large")
        form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
        if not hmac.compare_digest(form.get("csrf", ""), csrf):
            raise HTTPException(403, "bad CSRF token")
        rid = enqueue_local(form.get("repo_path", ""), form.get("base") or None, form.get("head") or "HEAD", False)
        return RedirectResponse(f"/runs/{rid}", status_code=303)

    return app
