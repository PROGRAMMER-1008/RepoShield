"""Agent action gateway: fail-closed, signed, single-use authorization bound to the exact action.

Flow: agent proposes action -> canonicalise + hash -> policy decision -> HMAC-signed token
      -> executor re-verifies (signature, expiry, exact action hash, policy hash, capability, nonce) -> sandbox.
"""
from __future__ import annotations

import base64
import fnmatch
import hmac
import json
import os
import secrets
import shlex
import time
import hashlib

from .audit import AuditLog
from .sandbox import Limits
from .util import canonical_json, sha256_hex


class Denied(Exception):
    pass


def canonical_action(command: str | list, cwd: str = ".", action_type: str = "EXECUTE_COMMAND") -> dict:
    argv = shlex.split(command, posix=(os.name != "nt")) if isinstance(command, str) else list(command)
    return {"schema_version": 1, "type": action_type, "argv": argv, "cwd": os.path.normpath(cwd)}


def action_hash(action: dict) -> str:
    return sha256_hex(canonical_json(action))


def required_capability(action: dict) -> str:
    argv = action["argv"]
    joined = " ".join(argv)
    if joined.startswith(("pytest", "python -m pytest", "python3 -m pytest")):
        return "test_execute"
    return "execute"


def load_key(state_dir: str) -> bytes:
    env = os.environ.get("REPOSHIELD_SIGNING_KEY")
    if env:
        return env.encode()
    path = os.path.join(state_dir, "signing.key")
    if not os.path.exists(path):
        os.makedirs(state_dir, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(secrets.token_hex(32))
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip().encode()


def _check_policy(action: dict, cfg: dict, workspace: str) -> str | None:
    """Return a denial reason, or None if the policy allows the action (default-deny)."""
    if action.get("schema_version") != 1 or action.get("type") != "EXECUTE_COMMAND":
        return "unsupported legacy action schema or type; typed actions require the controlled broker"
    argv = action["argv"]
    if not argv:
        return "empty command"
    cmd = " ".join(argv)
    acts = cfg.get("actions", {})
    for pat in acts.get("deny", []):
        if fnmatch.fnmatchcase(cmd, pat):
            return f"command matches deny pattern '{pat}'"
    for pol in cfg.get("policies") or []:
        for rule in pol.get("rules", []):
            if rule.get("type") == "forbidden_command":
                for pat in rule["patterns"]:
                    if fnmatch.fnmatchcase(cmd, pat):
                        return f"policy {pol['id']} forbids '{pat}'"
    if action["cwd"].startswith("..") or os.path.isabs(action["cwd"]):
        return "working directory escapes the workspace"
    for a in argv[1:]:
        if ".." in a.replace("\\", "/").split("/"):
            return f"argument '{a}' contains a parent-directory traversal"
        if (os.path.isabs(a) or a.startswith(("/", "\\"))) and not os.path.realpath(a).startswith(os.path.realpath(workspace)):
            return f"argument '{a}' is an absolute path outside the workspace"
    if not any(fnmatch.fnmatchcase(cmd, pat) for pat in acts.get("allow", [])):
        return "command is not on the allow list (default deny)"
    return None


def authorize(action: dict, cfg: dict, pol_hash: str, key: bytes, workspace: str, audit: AuditLog | None = None,
              ttl: int | None = None) -> str:
    ah = action_hash(action)
    reason = _check_policy(action, cfg, workspace)
    if reason:
        if audit:
            audit.append("COMMAND_DENIED", "gateway", {"action_hash": ah, "argv": action["argv"], "reason": reason})
        raise Denied(reason)
    max_ttl = int(cfg.get("actions", {}).get("max_ttl_seconds", 60))
    ttl = min(ttl or max_ttl, max_ttl)
    now = int(time.time())
    payload = {"v": 1, "decision_id": "dec_" + secrets.token_hex(6), "action_hash": ah,
               "capabilities": [required_capability(action)], "policy_hash": pol_hash,
               "workspace": hashlib.sha256(os.path.realpath(workspace).encode()).hexdigest()[:16],
               "iat": now, "exp": now + ttl, "nonce": secrets.token_hex(8)}
    body = base64.urlsafe_b64encode(canonical_json(payload).encode()).decode()
    sig = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
    if audit:
        audit.append("COMMAND_AUTHORIZED", "gateway", {"decision_id": payload["decision_id"], "action_hash": ah,
                                                       "argv": action["argv"], "expires": payload["exp"]})
    return f"{body}.{sig}"


def verify_token(token: str, action: dict, pol_hash: str, key: bytes, workspace: str, state_dir: str,
                 now: float | None = None, consume: bool = True) -> dict:
    """Raise Denied unless every binding holds. Single-use: the nonce is burned on success."""
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        raise Denied("malformed token")
    expect = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        raise Denied("invalid signature")
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode()))
    except Exception:
        raise Denied("malformed token payload")
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise Denied("unsupported authorization schema version")
    if action.get("schema_version") != 1 or action.get("type") != "EXECUTE_COMMAND":
        raise Denied("unsupported legacy action schema or type")
    if (now or time.time()) > payload["exp"]:
        raise Denied("authorization expired")
    if payload["action_hash"] != action_hash(action):
        raise Denied("action does not match the authorized action hash")
    if payload["policy_hash"] != pol_hash:
        raise Denied("policy changed since authorization")
    if payload["workspace"] != hashlib.sha256(os.path.realpath(workspace).encode()).hexdigest()[:16]:
        raise Denied("token was issued for a different workspace")
    if required_capability(action) not in payload["capabilities"]:
        raise Denied("token lacks the required capability")
    used = os.path.join(state_dir, "used_nonces.txt")
    os.makedirs(state_dir, exist_ok=True)
    seen = set(open(used, encoding="utf-8").read().split()) if os.path.exists(used) else set()
    if payload["nonce"] in seen:
        raise Denied("token already used (replay)")
    if consume:
        with open(used, "a", encoding="utf-8") as fh:
            fh.write(payload["nonce"] + "\n")
    return payload


def execute(token: str, action: dict, cfg: dict, pol_hash: str, key: bytes, workspace: str, state_dir: str,
            sandbox, audit: AuditLog | None = None, limits: Limits | None = None):
    ah = action_hash(action)
    try:
        payload = verify_token(token, action, pol_hash, key, workspace, state_dir)
    except Denied as e:
        if audit:
            audit.append("EXECUTION_DENIED", "gateway", {"action_hash": ah, "reason": str(e)})
        raise
    argv = list(action["argv"])
    if argv and argv[0] in ("python", "python3", "pytest"):
        argv = [sandbox.python] + argv[1:] if argv[0] != "pytest" else [sandbox.python, "-m", "pytest"] + argv[1:]
    cwd = os.path.join(workspace, action["cwd"])
    res = sandbox.run(argv, cwd, limits=limits or Limits(timeout_seconds=int(cfg["verification"]["timeout_seconds"])))
    if audit:
        audit.append("COMMAND_EXECUTED", sandbox.name, {"decision_id": payload["decision_id"], "action_hash": ah,
                                                        "exit_code": res.exit_code, "duration_ms": res.duration_ms,
                                                        "timed_out": res.timed_out})
    return res
