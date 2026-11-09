"""Executor-scoped lifecycle observations; candidates never have these credentials."""
import json
import sqlalchemy as sa
from fastapi import HTTPException

from .schema_v1 import executions
from .authorization_service import decision_row, current_authority
from ..evidence import redact


class ExecutionService:
    def __init__(self, policy):
        self.policy = policy

    def owned(self, c, execution_id, actor, lock=False):
        query = sa.select(executions).where(executions.c.id == execution_id)
        row = c.execute(query.with_for_update() if lock else query).mappings().first()
        if row is None: raise HTTPException(404, "execution not found")
        decision = decision_row(c, row["decision_id"])
        if (actor.role != "executor" or row["outcome"].get("executor") != actor.id
                or decision["request"]["tenant_id"] != actor.tenant_id
                or decision["request"]["repository_id"] not in actor.repository_ids):
            raise HTTPException(404, "execution not found")
        return row, decision

    def status(self, execution_id, actor):
        with self.policy.store.engine.begin() as c:
            row, decision = self.owned(c, execution_id, actor)
            active = row["state"] == "unknown-outcome"
            if active:
                try: current_authority(self.policy, c, decision)
                except HTTPException: active = False
            return {"active": active, "state": row["state"]}

    def finish(self, execution_id, actor, state, outcome):
        if state not in ("completed", "failed-infrastructure", "cancelled") or len(json.dumps(outcome).encode()) > 262144:
            raise HTTPException(422, "invalid or oversized execution result")
        # The executor identity is authoritative, not a candidate-supplied outcome field.
        try:
            outcome = {**redact(outcome), "executor": actor.id}
        except (ValueError, RecursionError):
            raise HTTPException(422, "invalid execution result") from None
        with self.policy.store.engine.begin() as c:
            row, decision = self.owned(c, execution_id, actor, lock=True)
            if row["state"] != "unknown-outcome":
                if row["state"] == state and row["outcome"] == outcome:
                    return {"state": state}
                raise HTTPException(409, "terminal execution is immutable")
            if state == "completed":
                try:
                    current_authority(self.policy, c, decision)
                except HTTPException:
                    state = "cancelled"
                    outcome = {"executor": actor.id, "error": "context_changed_before_completion"}
            c.execute(executions.update().where(executions.c.id == execution_id).values(state=state, outcome=outcome))
            self.policy.store._event(c, "EXECUTION_FINISHED", actor.id,
                {"execution_id": execution_id, "state": state}, session=decision["request"]["session_id"])
            return {"state": state}
