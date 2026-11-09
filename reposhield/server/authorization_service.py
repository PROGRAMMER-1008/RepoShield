"""Issuance and one-shot claims. No subprocesses, sandbox or external effects."""
from pathlib import Path

import sqlalchemy as sa
from fastapi import HTTPException

from ..action_policy import digest
from ..authorization import AuthorizationPayload, ExecutionProfile, verify_token
from ..contracts import ActionRequest, Contract
from .action_service import ActionService
from .durable import uid
from .schema_v1 import decisions, action_requests, executions, repositories
from .schema_v2 import approvals
from .schema_v3 import authorizations


def current_authority(policy, c, row):
    body = ActionRequest.model_validate(row["request"])
    context, verdict, _, now = policy._context(c, body, row["payload"]["requested_by"])
    if (row["expires_at"] <= now or digest(context) != row["policy_digest"]
            or verdict["decision"] != row["decision"] or verdict["decision"] == "DENY"):
        raise HTTPException(409, "decision expired, denied or context changed")
    approval_digest = None
    if verdict["decision"] == "REVIEW_REQUIRED":
        approval = c.execute(sa.select(approvals).where(approvals.c.decision_id == row["id"])).mappings().first()
        if (approval is None or approval["context_digest"] != row["policy_digest"]
                or approval["actor_id"] == row["payload"]["requested_by"]):
            raise HTTPException(409, "current independent approval required")
        approval_digest = digest({**dict(approval), "created_at": approval["created_at"].isoformat()})
    resource = context["resource"]
    profile_name = body.action.profile if body.action.action_type == "RUN_TESTS" else resource["default_profile"]
    profile = resource["execution_profiles"].get(profile_name)
    if profile is None or any(profile_name not in s["profiles"] for s in
                              (resource["administrator"], resource["repository"], context["scope"])):
        raise HTTPException(409, "trusted execution profile is missing or outside scope")
    return body, context, ExecutionProfile.model_validate(profile), profile_name, approval_digest, now


def decision_row(c, decision_id):
    row = c.execute(sa.select(decisions, action_requests.c.payload.label("request"))
                    .join(action_requests).where(decisions.c.id == decision_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "decision not found")
    return row


class IssuanceService:
    def __init__(self, policy: ActionService, private_path, key_id):
        self.policy, self.private_path, self.key_id = policy, private_path, key_id

    def issue(self, decision_id, actor):
        if not self.private_path or not self.key_id:
            raise HTTPException(501, "authorization signer is not configured")
        with self.policy.store.engine.begin() as c:
            row = decision_row(c, decision_id)
            if (actor.role == "viewer" or row["payload"]["requested_by"] != actor.id
                    or row["request"]["tenant_id"] != actor.tenant_id
                    or row["request"]["repository_id"] not in actor.repository_ids):
                raise HTTPException(403, "only the scoped requester can obtain authorization")
            body, context, profile, name, approval, now = current_authority(self.policy, c, row)
            previous = c.scalar(sa.select(authorizations.c.token).where(authorizations.c.decision_id == decision_id))
            if previous is not None:
                return previous  # Never extend expiry or mint a second nonce.
            from .signing import DecisionSigner
            try:
                roots = c.scalars(sa.select(repositories.c.path)).all()
                roots.append(str(Path(__file__).resolve().parents[2]))
                signer = DecisionSigner(self.private_path, self.key_id, roots)
                payload = AuthorizationPayload(decision_id=decision_id, nonce=uid(), requested_by=actor.id,
                    request=body, resource_id=context["resource"]["resource_id"], profile_name=name,
                    profile=profile, policy_digest=row["policy_digest"], policy_epoch=row["policy_epoch"],
                    revocation_epoch=context["revocation_epoch"], approval_digest=approval,
                    issued_at=int(now.timestamp()), expires_at=int(row["expires_at"].timestamp()))
                token = signer.sign(payload).model_dump(mode="json")
            except (OSError, ValueError, TypeError):
                raise HTTPException(503, "authorization signer unavailable or invalid") from None
            if payload.expires_at <= payload.issued_at:
                raise HTTPException(409, "decision expires too soon")
            c.execute(decisions.update().where(decisions.c.id == decision_id).values(nonce=payload.nonce))
            c.execute(authorizations.insert().values(decision_id=decision_id, token=token))
            self.policy.store._event(c, "AUTHORIZATION_ISSUED", actor.id,
                {"decision_id": decision_id, "key_id": self.key_id}, session=body.session_id)
            return token


class ClaimService:
    """Trusted coordinator claim adapter; takes only verification keys.

    Executors use the authenticated claim API, never database credentials. A
    committed claim defaults to unknown-outcome before handing control to a broker.
    No recovery loop retries these rows; RS2 06 will supply terminal evidence.
    """
    def __init__(self, policy, public_keys):
        self.policy, self.public_keys = policy, public_keys

    def claim(self, token_value, request, resource_id, profile, executor):
        with self.policy.store.engine.begin() as c:
            now = c.scalar(sa.select(sa.func.clock_timestamp()))
            try:
                token = verify_token(token_value, self.public_keys, audience=executor.id, now=int(now.timestamp()))
            except ValueError:
                raise HTTPException(403, "invalid authorization") from None
            p = token.payload
            if (executor.role != "executor" or executor.tenant_id != p.request.tenant_id
                    or p.request.repository_id not in executor.repository_ids or p.request != request
                    or p.resource_id != resource_id or p.profile != profile):
                raise HTTPException(403, "execution context does not match authorization")
            row = decision_row(c, p.decision_id)
            body, context, current_profile, name, approval, now = current_authority(self.policy, c, row)
            # Recheck expiry after acquiring locks; waiting cannot extend validity.
            stored = c.scalar(sa.select(authorizations.c.token).where(authorizations.c.decision_id == p.decision_id))
            now = c.scalar(sa.select(sa.func.clock_timestamp()))
            if (int(now.timestamp()) >= p.expires_at or stored != token.model_dump(mode="json")
                    or row["nonce"] != p.nonce or body != p.request
                    or row["payload"]["requested_by"] != p.requested_by
                    or digest(context) != p.policy_digest or row["policy_epoch"] != p.policy_epoch
                    or context["revocation_epoch"] != p.revocation_epoch
                    or context["resource"]["resource_id"] != p.resource_id
                    or current_profile != p.profile or name != p.profile_name or approval != p.approval_digest):
                raise HTTPException(409, "authorization context changed")
            # _context holds the session lock, serializing claims for this session;
            # the database additionally enforces unique execution per decision.
            if c.scalar(sa.select(executions.c.id).where(executions.c.decision_id == p.decision_id)):
                raise HTTPException(409, "authorization already claimed; never replay")
            execution_id = uid()
            c.execute(executions.insert().values(id=execution_id, decision_id=p.decision_id,
                state="unknown-outcome", outcome={"reason": "claimed_without_terminal_evidence", "executor": executor.id}))
            self.policy.store._event(c, "AUTHORIZATION_CLAIMED", executor.id,
                {"decision_id": p.decision_id, "execution_id": execution_id}, session=body.session_id)
            return {"execution_id": execution_id, "state": "unknown-outcome", "execution_enabled": False}
