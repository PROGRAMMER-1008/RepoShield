"""Versioned Ed25519 wire format. Verification needs public keys only."""
import base64
import json
import re
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field

from .contracts import Contract, ActionRequest


class ExecutionProfile(Contract):
    image: str = Field(pattern=r"^[^\s@]+@sha256:[0-9a-f]{64}$", max_length=512)
    executor_audience: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    timeout_seconds: int = Field(strict=True, ge=1, le=600)
    memory_mb: int = Field(strict=True, ge=32, le=4096)
    cpu_millis: int = Field(strict=True, ge=100, le=2000)
    pids: int = Field(strict=True, ge=1, le=256)
    disk_mb: int = Field(strict=True, ge=1, le=1024)
    output_bytes: int = Field(strict=True, ge=1, le=1048576)
    uid: int = Field(strict=True, ge=1, le=65535)
    network: Literal["deny"] = "deny"
    read_only_root: Literal[True] = True


class AuthorizationPayload(Contract):
    decision_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    requested_by: str = Field(min_length=1, max_length=64)
    request: ActionRequest
    resource_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    profile_name: str = Field(min_length=1, max_length=256)
    profile: ExecutionProfile
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_epoch: int = Field(strict=True, ge=1)
    revocation_epoch: int = Field(strict=True, ge=0)
    approval_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    issued_at: int = Field(strict=True, ge=0)
    expires_at: int = Field(strict=True, ge=0)


class SignedAuthorization(Contract):
    version: Literal[1] = 1
    algorithm: Literal["Ed25519"] = "Ed25519"
    key_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    payload: AuthorizationPayload
    signature: str = Field(pattern=r"^[A-Za-z0-9_-]{86}$")


def canonical(value):
    """RS authorization v1: ASCII JSON, sorted keys, no whitespace/NaN/floats.

    Schemas contain strings, integers, booleans, arrays, objects and null only.
    Every signed field is emitted, including defaults. Domain prevents reuse by
    another signing protocol. Do not change this format without a new version.
    """
    return b"RepoShield.Authorization.v1\x00" + json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def signing_bytes(token):
    return canonical(token.model_dump(mode="json", exclude={"signature"}))


def verify_token(value, public_keys: dict[str, Ed25519PublicKey], *, audience, now):
    try:
        token = SignedAuthorization.model_validate(value)
        raw = base64.b64decode(token.signature + "==", altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != token.signature:
            raise ValueError("noncanonical signature")
        public_keys[token.key_id].verify(raw, signing_bytes(token))
        p = token.payload
        if (p.profile.executor_audience != audience or not p.issued_at <= now < p.expires_at
                or not 0 < p.expires_at - p.issued_at <= 300):
            raise ValueError("audience or lifetime mismatch")
        return token
    except (ValueError, KeyError, InvalidSignature, TypeError) as exc:
        raise ValueError("invalid authorization") from exc


def load_public_keys(path, workspace_roots):
    resolved = Path(path).resolve(strict=True)
    if any(resolved.is_relative_to(Path(root).resolve()) for root in workspace_roots):
        raise ValueError("verification keys must be outside workspaces")
    with resolved.open("rb") as f:
        raw = f.read(65537)
    if len(raw) > 65536:
        raise ValueError("verification key file too large")
    keys = json.loads(raw)
    if not isinstance(keys, dict) or not keys:
        raise ValueError("verification keys required")
    result = {}
    for kid, value in keys.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", kid):
            raise ValueError("invalid key ID")
        result[kid] = Ed25519PublicKey.from_public_bytes(base64.b64decode(value, validate=True))
    return result
