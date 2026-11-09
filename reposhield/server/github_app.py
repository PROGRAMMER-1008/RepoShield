"""Trusted GitHub.com App client. No credentials in repository or execution inputs."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import BaseModel, ConfigDict, Field


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    app_id: int = Field(strict=True, gt=0)
    installation_id: int = Field(strict=True, gt=0)
    remote_repository_id: int = Field(strict=True, gt=0)
    repository_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    full_name: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    private_key_file: str
    webhook_secret_file: str


def external_bytes(path, roots, limit):
    resolved = Path(path).resolve(strict=True)
    if any(resolved.is_relative_to(Path(root).resolve()) for root in roots):
        raise ValueError("GitHub configuration and credentials must be outside workspaces")
    with resolved.open("rb") as stream: data = stream.read(limit + 1)
    if len(data) > limit: raise ValueError("GitHub configuration limit")
    return data


def load_config(path, roots):
    return AppConfig.model_validate_json(external_bytes(path, roots, 16384))


class GitHubError(RuntimeError):
    pass


class AccessRevoked(GitHubError):
    pass


class AppClient:
    def __init__(self, config, roots, transport=None):
        self.config, self.roots = config, roots
        self.transport = transport or self.http

    @staticmethod
    def http(method, url, headers, body):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs): return None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024: raise GitHubError("response_limit")
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            return error.code, {}
        except (OSError, ValueError):
            raise GitHubError("github_transport_failed") from None

    def jwt(self):
        key = serialization.load_pem_private_key(external_bytes(self.config.private_key_file, self.roots, 16384), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("GitHub App requires an RSA private key of at least 2048 bits")
        def encode(value): return base64.urlsafe_b64encode(value).rstrip(b"=")
        now = int(time.time())
        raw = encode(b'{"alg":"RS256","typ":"JWT"}') + b"." + encode(json.dumps(
            {"iat": now - 60, "exp": now + 480, "iss": str(self.config.app_id)}, separators=(",", ":")).encode())
        return (raw + b"." + encode(key.sign(raw, padding.PKCS1v15(), hashes.SHA256()))).decode()

    def call(self, method, path, token, payload=None):
        if not path.startswith("/") or path.startswith("//") or ".." in path:
            raise GitHubError("invalid_api_path")
        status, result = self.transport(method, "https://api.github.com" + path,
            {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
             "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "reposhield", "Content-Type": "application/json"},
            json.dumps(payload).encode() if payload is not None else None)
        if status in (401, 403, 404): raise AccessRevoked("github_access_unavailable")
        if status not in (200, 201, 204): raise GitHubError("github_request_failed")
        if not isinstance(result, dict): raise GitHubError("invalid_github_response")
        return result

    def installation_token(self):
        cfg, jwt = self.config, self.jwt()
        installation = self.call("GET", f"/app/installations/{cfg.installation_id}", jwt)
        if (installation.get("id") != cfg.installation_id or installation.get("app_id") != cfg.app_id
                or installation.get("suspended_at") is not None):
            raise AccessRevoked("installation_inactive")
        data = self.call("POST", f"/app/installations/{cfg.installation_id}/access_tokens", jwt,
            {"repository_ids": [cfg.remote_repository_id],
             "permissions": {"contents": "read", "pull_requests": "read", "checks": "write"}})
        token = data.get("token")
        if not isinstance(token, str) or not token or len(token) > 4096: raise GitHubError("invalid_installation_token")
        repository = self.call("GET", f"/repos/{cfg.full_name}", token)
        if (repository.get("id") != cfg.remote_repository_id or repository.get("full_name", "").lower() != cfg.full_name.lower()
                or repository.get("private") is not False):
            raise AccessRevoked("only_registered_public_repository_supported")
        return token

    def pull(self, number, token):
        if type(number) is not int or number <= 0: raise GitHubError("invalid_pr")
        value = self.call("GET", f"/repos/{self.config.full_name}/pulls/{number}", token)
        try:
            if value["number"] != number or value["base"]["repo"]["id"] != self.config.remote_repository_id:
                raise ValueError()
            for part in ("head", "base"):
                if not re.fullmatch(r"[0-9a-f]{40}", value[part]["sha"]): raise ValueError()
            ref = value["base"]["ref"]
            if not re.fullmatch(r"[A-Za-z0-9_./-]+", ref) or ".." in ref or ref.startswith(("/", "-")):
                raise ValueError()
        except (KeyError, TypeError, ValueError): raise GitHubError("invalid_pr_context") from None
        return value


def fetch_public(repo, config, pull):
    """Fetch only public GitHub refs into an administrator-owned registered mirror.

    No installation token is supplied to Git; no candidate checkout or hooks run.
    Local repository configuration is administrator-owned, never candidate-controlled.
    """
    env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="")
    def git(*args):
        result = subprocess.run(["git", "-C", repo["path"], "-c", "credential.helper=", "-c", "core.hooksPath=/dev/null",
            "-c", "core.fsmonitor=false", "-c", "protocol.file.allow=never", "-c", "protocol.ext.allow=never",
            *args], env=env, capture_output=True, timeout=45)
        if result.returncode: raise GitHubError("public_fetch_failed")
        return result.stdout.decode().strip()
    number = pull["number"]
    if git("rev-parse", "--is-bare-repository") != "true":
        raise GitHubError("registered_public_mirror_must_be_bare")
    git("fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "https://github.com/" + config.full_name + ".git",
        f"+refs/heads/{pull['base']['ref']}:refs/reposhield/base",
        f"+refs/pull/{number}/head:refs/reposhield/pr-{number}")
    if git("rev-parse", "refs/reposhield/base") != pull["base"]["sha"] or git("rev-parse", f"refs/reposhield/pr-{number}") != pull["head"]["sha"]:
        raise GitHubError("refs_changed_during_fetch")
    merge_base = git("merge-base", pull["base"]["sha"], pull["head"]["sha"])
    if not re.fullmatch(r"[0-9a-f]{40}", merge_base): raise GitHubError("invalid_merge_base")
    return merge_base
