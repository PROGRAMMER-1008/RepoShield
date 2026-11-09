"""Deterministic policy evaluation. No filesystem access, shell or execution."""
import hashlib
import json
import re
from typing import Literal

from pydantic import Field, field_validator
from .contracts import Contract, ActionRequest
from .authorization import ExecutionProfile


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def safe_path(path):
    # One portable spelling; reject Windows devices, ADS, traversal and metadata.
    parts = path.split("/")
    return bool(path) and all(
        re.fullmatch(r"[A-Za-z0-9_.-]+", p) and p not in (".", "..")
        and not p.endswith((".", " ")) and not p.startswith(".")
        and p.split(".")[0].upper() not in
        {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
        for p in parts)


class Scope(Contract):
    actions: tuple[Literal["READ_FILE", "APPLY_PATCH", "RUN_TESTS"], ...] = ()
    paths: tuple[str, ...] = Field(default=(), max_length=1000)
    profiles: tuple[str, ...] = ()
    max_bytes: int = Field(default=65536, strict=True, gt=0, le=1048576)

    @field_validator("paths")
    @classmethod
    def paths_are_exact(cls, paths):
        if not all(safe_path(p) for p in paths):
            raise ValueError("scope paths must be exact portable relative paths")
        return paths


class Resource(Contract):
    resource_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    tenant_id: str
    repository_id: str
    workspace_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_epoch: int = Field(strict=True, ge=1)
    administrator: Scope
    repository: Scope
    sessions: dict[str, Scope]
    execution_profiles: dict[str, ExecutionProfile] = Field(default_factory=dict)
    default_profile: str | None = None


class PolicyFile(Contract):
    schema_version: Literal[1]
    resources: tuple[Resource, ...]


def patch_paths(patch):
    """Accept only ordinary unified modifications, with fully counted hunks.

    No creates/deletes, renames, mode changes, binary diffs or ambiguous headers.
    Application against immutable source and link checks belong to the executor.
    """
    lines = patch.splitlines()
    paths, i = [], 0
    while i < len(lines):
        if not lines[i].startswith("--- a/") or i + 2 >= len(lines):
            raise ValueError("unsupported patch format")
        path = lines[i][6:]
        if not safe_path(path) or lines[i + 1] != "+++ b/" + path or path in paths:
            raise ValueError("ambiguous patch path")
        paths.append(path)
        i += 2
        hunks = 0
        while i < len(lines) and lines[i].startswith("@@"):
            m = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[i])
            if not m:
                raise ValueError("invalid hunk")
            old, new = int(m[2] or 1), int(m[4] or 1)
            i += 1
            while old or new:
                if i >= len(lines) or not lines[i] or lines[i][0] not in " +-":
                    raise ValueError("incomplete hunk")
                kind = lines[i][0]
                old -= kind in " -"
                new -= kind in " +"
                if old < 0 or new < 0:
                    raise ValueError("invalid hunk counts")
                i += 1
            hunks += 1
        if not hunks:
            raise ValueError("patch has no hunks")
    if not paths:
        raise ValueError("empty patch")
    return paths


def evaluate(request: ActionRequest, resource: Resource, session_scope: Scope):
    def result(decision, reason, paths=()):
        return {"decision": decision, "reason": reason, "paths": list(paths),
                "resource_id": resource.resource_id, "execution_enabled": False}
    action = request.action
    kind = action.action_type
    if kind not in ("READ_FILE", "APPLY_PATCH", "RUN_TESTS"):
        return result("DENY", "unsupported_action")
    if (request.tenant_id != resource.tenant_id or request.repository_id != resource.repository_id
            or request.workspace_revision != resource.workspace_revision):
        return result("DENY", "resource_context_mismatch")
    if request.requested_capabilities:
        return result("DENY", "additional_capabilities_not_supported")
    scopes = (resource.administrator, resource.repository, session_scope)
    if any(kind not in s.actions for s in scopes):
        return result("DENY", "action_outside_intersection")
    try:
        paths = (patch_paths(action.patch) if kind == "APPLY_PATCH" else
                 list(action.test_paths) if kind == "RUN_TESTS" else [action.path])
    except ValueError:
        return result("DENY", "invalid_patch")
    if any(not safe_path(p) or any(p not in s.paths for s in scopes) for p in paths):
        return result("DENY", "path_outside_intersection")
    size = len(action.patch.encode()) if kind == "APPLY_PATCH" else action.max_bytes if kind == "READ_FILE" else 0
    if any(size > s.max_bytes for s in scopes):
        return result("DENY", "size_limit")
    if kind == "RUN_TESTS" and any(action.profile not in s.profiles for s in scopes):
        return result("DENY", "profile_outside_intersection")
    if kind == "APPLY_PATCH" and any(p.startswith("docs/") for p in paths):
        if not all(p.startswith("docs/") and p.endswith(".md") for p in paths):
            return result("DENY", "mixed_or_unsupported_document_patch")
        return result("REVIEW_REQUIRED", "documentation_patch", paths)
    return result("ALLOW", "policy_satisfied", paths)
