"""Administrator-configured local identities. Tokens are never stored in plaintext."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=64)
    role: Literal["administrator", "reviewer", "viewer", "agent"]
    repository_ids: tuple[str, ...] = Field(min_length=1, max_length=1000)
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExecutorIdentity(Identity):
    role: Literal["executor"] = "executor"


def load_identities(path, model=Identity):
    if not path:
        raise RuntimeError("REPOSHIELD_IDENTITIES_FILE is required; anonymous access is disabled")
    raw = Path(path).read_bytes()
    if len(raw) > 1048576:
        raise ValueError("Identity configuration is too large")
    items = [model.model_validate(x) for x in json.loads(raw)]
    if not items or len({i.id for i in items}) != len(items) or len({i.token_sha256 for i in items}) != len(items):
        raise ValueError("Identity IDs and token hashes must be distinct and nonempty")
    return tuple(items)


def authenticate(identities, token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    return next((i for i in identities if hmac.compare_digest(i.token_sha256, digest)), None)
