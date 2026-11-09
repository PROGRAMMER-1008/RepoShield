"""GitHub.com login for a single trusted coordinator process; no browser API tokens."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import threading
import time
from typing import Literal
from urllib.parse import urlencode, urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
import sqlalchemy as sa

from .github_app import AppClient, external_bytes
from .identities import Identity
from .schema_v1 import repositories


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    github_id: int = Field(strict=True, gt=0)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    role: Literal["administrator", "reviewer", "viewer"]
    repository_ids: tuple[str, ...] = Field(min_length=1, max_length=1000)


class BrowserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    client_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    client_secret_file: str
    origin: str
    allow_loopback_http: bool = False
    organization: str = Field(pattern=r"^[A-Za-z0-9-]{1,100}$")
    organization_id: int = Field(strict=True, gt=0)
    tenant_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    members: tuple[Member, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_boundary(self):
        u = urlsplit(self.origin)
        if (u.scheme not in ("https", "http") or not u.hostname or u.username or u.password
                or u.path or u.query or u.fragment or u.netloc != u.netloc.lower()
                or any(ch.isspace() for ch in self.origin)):
            raise ValueError("origin must be a canonical HTTP(S) origin")
        if u.scheme != "https" and not (self.allow_loopback_http and u.hostname in ("127.0.0.1", "localhost", "::1")):
            raise ValueError("HTTPS required except explicit loopback development")
        if len({m.github_id for m in self.members}) != len(self.members) or len({m.id for m in self.members}) != len(self.members):
            raise ValueError("duplicate browser identity")
        return self


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


class BrowserAuth:
    """Bounded process-local sessions. Restart/reconfiguration revokes every login."""
    def __init__(self, store, path):
        self.store, self.path = store, path
        self.lock = threading.Lock()
        self.pending, self.sessions = {}, {}
        self.transport = AppClient.http
        self.clock = time.monotonic
        if path:
            self.config()  # fail startup closed for invalid configured credentials

    def config(self):
        if not self.path:
            raise HTTPException(503, "GitHub sign-in is not configured")
        try:
            with self.store.engine.connect() as c:
                roots = c.scalars(sa.select(repositories.c.path)).all()
            roots.append(str(Path(__file__).resolve().parents[2]))
            raw = external_bytes(self.path, roots, 262144)
            cfg = BrowserConfig.model_validate_json(raw)
            secret = external_bytes(cfg.client_secret_file, roots, 4096).decode().strip()
            if not secret or any(ch.isspace() for ch in secret):
                raise ValueError("invalid OAuth secret")
            return cfg, hashed(raw.decode() + secret), secret
        except (OSError, ValueError, UnicodeError):
            raise HTTPException(503, "GitHub sign-in configuration unavailable") from None

    @staticmethod
    def cookie_name(cfg, purpose="session"):
        return ("__Host-rs_" if cfg.origin.startswith("https:") else "rs_dev_") + purpose

    def cookie(self, response, cfg, value, purpose="session", age=900):
        response.set_cookie(self.cookie_name(cfg, purpose), value, max_age=age,
            secure=cfg.origin.startswith("https:"), httponly=True, samesite="lax", path="/")

    def check_origin(self, request, cfg, mutation=False):
        if str(request.base_url).rstrip("/") != cfg.origin:
            raise HTTPException(400, "Browser origin does not match configured origin")
        if mutation and request.headers.get("origin") != cfg.origin:
            raise HTTPException(403, "Same-origin form required")

    def prune(self):
        now = self.clock()
        for table in (self.pending, self.sessions):
            for key in list(table):
                if table[key]["until"] <= now:
                    del table[key]

    def begin(self, request):
        cfg, fingerprint, _ = self.config()
        self.check_origin(request, cfg)
        state, browser, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        with self.lock:
            self.prune()
            if len(self.pending) >= 256:
                raise HTTPException(429, "Too many pending sign-ins; retry later")
            self.pending[hashed(state)] = dict(browser=hashed(browser), verifier=verifier,
                config=fingerprint, until=self.clock() + 300)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        url = "https://github.com/login/oauth/authorize?" + urlencode(dict(client_id=cfg.client_id,
            redirect_uri=cfg.origin + "/ui/auth/callback", scope="read:org", state=state,
            code_challenge=challenge, code_challenge_method="S256", allow_signup="false"))
        return cfg, browser, url

    def complete(self, request):
        cfg, fingerprint, secret = self.config()
        self.check_origin(request, cfg)
        states, codes = request.query_params.getlist("state"), request.query_params.getlist("code")
        if len(states) != 1 or len(codes) != 1 or not codes[0] or len(codes[0]) > 1024 or len(states[0]) > 128:
            raise HTTPException(400, "Sign-in was cancelled or invalid; start again")
        with self.lock:
            self.prune()
            pending = self.pending.pop(hashed(states[0]), None)
        browser = request.cookies.get(self.cookie_name(cfg, "login"), "")
        if (pending is None or pending["config"] != fingerprint or not browser
                or not hmac.compare_digest(pending["browser"], hashed(browser))):
            raise HTTPException(403, "Sign-in expired or browser binding invalid; start again")
        try:
            headers = {"Accept": "application/json", "User-Agent": "reposhield", "Content-Type": "application/json"}
            status, result = self.transport("POST", "https://github.com/login/oauth/access_token", headers,
                json.dumps(dict(client_id=cfg.client_id, client_secret=secret, code=codes[0],
                    redirect_uri=cfg.origin + "/ui/auth/callback", code_verifier=pending["verifier"])).encode())
            if status != 200 or result.get("token_type", "").lower() != "bearer" or not result.get("access_token"):
                raise ValueError()
            token = result["access_token"]
            headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                       "User-Agent": "reposhield", "X-GitHub-Api-Version": "2026-03-10"}
            status, user = self.transport("GET", "https://api.github.com/user", headers, None)
            if status != 200 or type(user.get("id")) is not int:
                raise ValueError()
            member = next((m for m in cfg.members if m.github_id == user["id"]), None)
            status, org = self.transport("GET", "https://api.github.com/user/memberships/orgs/" + cfg.organization, headers, None)
            if (member is None or status != 200 or org.get("state") != "active"
                    or org.get("organization", {}).get("id") != cfg.organization_id
                    or org.get("user", {}).get("id") != member.github_id):
                raise ValueError()
        except Exception:
            # No upstream text, codes, access tokens or transport exception details escape.
            raise HTTPException(403, "GitHub sign-in or organization access could not be verified") from None
        # Re-read trusted grants after network calls; reject a concurrent revocation.
        if self.config()[1] != fingerprint:
            raise HTTPException(403, "Sign-in configuration changed; start again")
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.lock:
            self.prune()
            if len(self.sessions) >= 1024:
                raise HTTPException(429, "Too many sessions; retry later")
            self.sessions.pop(hashed(request.cookies.get(self.cookie_name(cfg), "")), None)
            self.sessions[hashed(sid)] = dict(member=member.github_id, config=fingerprint,
                csrf=csrf, until=self.clock() + 900)
        return cfg, sid

    def authenticate(self, request):
        cfg, fingerprint, _ = self.config()
        self.check_origin(request, cfg, request.method == "POST")
        key = hashed(request.cookies.get(self.cookie_name(cfg), ""))
        with self.lock:
            self.prune()
            session = self.sessions.get(key)
        if session is None or session["config"] != fingerprint:
            raise HTTPException(401, "Sign in to continue")
        member = next((m for m in cfg.members if m.github_id == session["member"]), None)
        if member is None:
            raise HTTPException(401, "Sign in to continue")
        # This identity never enters the bearer-token registry.
        actor = Identity(id=member.id, tenant_id=cfg.tenant_id, role=member.role,
                         repository_ids=member.repository_ids, token_sha256="0" * 64)
        return cfg, actor, session

    def logout(self, request, cfg):
        with self.lock:
            self.sessions.pop(hashed(request.cookies.get(self.cookie_name(cfg), "")), None)
