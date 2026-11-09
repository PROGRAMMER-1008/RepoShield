"""Trusted persistence adapter for policy decisions; never executes an action."""
from datetime import timedelta
from pathlib import Path

import sqlalchemy as sa
from fastapi import HTTPException

from ..action_policy import PolicyFile, Scope, digest, evaluate
from ..contracts import ActionRequest
from .durable import uid
from .schema_v1 import repositories, sessions, action_requests, decisions
from .schema_v2 import approvals


class ActionService:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def resource(self, repository_id, connection=None):
        if not self.path:
            raise HTTPException(501, "trusted action policy is not configured")
        try:
            path = Path(self.path).resolve(strict=True)
            if connection is None:
                with self.store.engine.connect() as c:
                    roots = c.scalars(sa.select(repositories.c.path)).all()
            else:
                roots = connection.scalars(sa.select(repositories.c.path)).all()
            if any(path.is_relative_to(Path(root).resolve()) for root in roots):
                raise ValueError("policy must be outside registered workspaces")
            with path.open("rb") as f:
                raw = f.read(1048577)
            if len(raw) > 1048576:
                raise ValueError("policy too large")
            policy = PolicyFile.model_validate_json(raw)
            ids = [r.repository_id for r in policy.resources]
            names = [r.resource_id for r in policy.resources]
            if len(set(ids)) != len(ids) or len(set(names)) != len(names):
                raise ValueError("duplicate resource")
            return next((r for r in policy.resources if r.repository_id == repository_id), None)
        except (ValueError, OSError):
            raise HTTPException(503, "trusted action policy unavailable or invalid") from None

    def scope_for(self, repository_id, actor_id):
        resource = self.resource(repository_id)
        return resource.sessions.get(actor_id, Scope()).model_dump(mode="json") if resource else Scope().model_dump(mode="json")

    def _context(self, c, body, actor_id):
        # Same lock order for authorization and approval. Revocation locks the session.
        repo = c.execute(sa.select(repositories).where(repositories.c.id == body.repository_id)
                         .with_for_update()).mappings().first()
        session = c.execute(sa.select(sessions).where(sessions.c.id == body.session_id)
                            .with_for_update()).mappings().first()
        now = c.scalar(sa.select(sa.func.clock_timestamp()))
        if (repo is None or session is None or session["repository_id"] != body.repository_id
                or repo["tenant_id"] != body.tenant_id or session["owner_id"] != actor_id
                or session["state"] != "active" or session["expires_at"] <= now):
            raise HTTPException(403, "invalid, revoked or expired action session")
        from .schema_v2 import session_scopes
        pinned = c.scalar(sa.select(session_scopes.c.payload).where(session_scopes.c.session_id == body.session_id))
        resource = self.resource(body.repository_id, c)
        if resource is None:
            raise HTTPException(403, "repository has no trusted action resource")
        scope = Scope.model_validate(pinned or {})
        # Current owner grant can narrow, but cannot enlarge the pinned session.
        current = resource.sessions.get(actor_id, Scope())
        scope = Scope(actions=tuple(a for a in scope.actions if a in current.actions),
                      paths=tuple(p for p in scope.paths if p in current.paths),
                      profiles=tuple(p for p in scope.profiles if p in current.profiles),
                      max_bytes=min(scope.max_bytes, current.max_bytes))
        context = {"resource": resource.model_dump(mode="json"), "scope": scope.model_dump(mode="json"),
                   "actor_id": actor_id, "revocation_epoch": session["revocation_epoch"],
                   "repository_epoch": repo["policy_epoch"]}
        verdict = evaluate(body, resource, scope)
        if resource.policy_epoch != repo["policy_epoch"]:
            verdict.update(decision="DENY", reason="policy_epoch_mismatch")
        return context, verdict, min(session["expires_at"], now + timedelta(minutes=5)), now

    def authorize(self, body, actor):
        if (actor.role == "viewer" or body.tenant_id != actor.tenant_id
                or body.repository_id not in actor.repository_ids):
            raise HTTPException(403, "identity cannot request this repository action")
        with self.store.engine.begin() as c:
            context, verdict, expiry, _ = self._context(c, body, actor.id)
            request_id, decision_id = uid(), uid()
            payload = body.model_dump(mode="json")
            c.execute(action_requests.insert().values(id=request_id, session_id=body.session_id,
                action_digest=digest(payload), payload=payload))
            response = {**verdict, "id": decision_id, "action_request_id": request_id,
                        "requested_by": actor.id, "context_digest": digest(context),
                        "action_digest": digest(payload), "expires_at": expiry.isoformat(),
                        "workspace_revision": body.workspace_revision}
            c.execute(decisions.insert().values(id=decision_id, action_request_id=request_id,
                decision=verdict["decision"], policy_digest=digest(context),
                policy_epoch=context["repository_epoch"], expires_at=expiry, payload=response))
            self.store._event(c, "ACTION_DECIDED", actor.id,
                {"decision_id": decision_id, "decision": verdict["decision"], "reason": verdict["reason"]},
                session=body.session_id)
            return response

    def approve(self, decision_id, actor):
        if actor.role not in ("reviewer", "administrator"):
            raise HTTPException(403, "reviewer role required")
        with self.store.engine.begin() as c:
            row = c.execute(sa.select(decisions, action_requests.c.payload.label("request"))
                .join(action_requests).where(decisions.c.id == decision_id)).mappings().first()
            if row is None:
                raise HTTPException(404, "decision not found")
            body = ActionRequest.model_validate(row["request"])
            if body.tenant_id != actor.tenant_id or body.repository_id not in actor.repository_ids:
                raise HTTPException(404, "decision not found")
            requester = row["payload"]["requested_by"]
            if requester == actor.id:
                raise HTTPException(403, "requesters cannot approve their own action")
            if row["decision"] != "REVIEW_REQUIRED" or row["payload"]["reason"] != "documentation_patch":
                raise HTTPException(409, "decision is not reviewable")
            context, verdict, _, now = self._context(c, body, requester)
            if (row["expires_at"] <= now or digest(context) != row["policy_digest"]
                    or verdict["decision"] != "REVIEW_REQUIRED"):
                raise HTTPException(409, "decision expired or context changed; request a new decision")
            # Session lock serializes simultaneous approvals. Raw decision never changes.
            existing = c.execute(sa.select(approvals).where(approvals.c.decision_id == decision_id)).mappings().first()
            if existing is None:
                c.execute(approvals.insert().values(decision_id=decision_id, actor_id=actor.id,
                    context_digest=row["policy_digest"]))
                self.store._event(c, "ACTION_APPROVED", actor.id, {"decision_id": decision_id}, session=body.session_id)
            return {"decision_id": decision_id, "raw_decision": "REVIEW_REQUIRED", "approved": True,
                    "approved_by": existing["actor_id"] if existing else actor.id, "execution_enabled": False}
