"""PostgreSQL transactions for verification jobs; never executes repository code."""
from __future__ import annotations

from datetime import timedelta
from contextlib import nullcontext
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from ..util import canonical_json, sha256_hex
from .schema_v1 import (repositories, runs, attempts, tasks, dependencies, sessions,
                        events, outbox)

STAGES = ("snapshot", "analyze", "tests", "aggregate", "publish")
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def uid():
    return uuid.uuid4().hex


class LeaseLost(RuntimeError):
    pass


class DurableStore:
    def __init__(self, url: str):
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("The durable coordinator requires PostgreSQL with psycopg")
        self.engine = sa.create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2,
                                      connect_args={"connect_timeout": 5})

    def check_schema(self):
        with self.engine.connect() as c:
            if c.scalar(sa.text("SELECT version_num FROM alembic_version")) != "0005":
                raise RuntimeError("Unsupported database schema; run the RepoShield migrations")

    @staticmethod
    def _event(c, kind, actor, data, attempt=None, session=None):
        c.execute(events.insert().values(kind=kind, actor_id=actor, data=data,
                                        attempt_id=attempt, session_id=session))

    def register_repository(self, *, repository_id, tenant_id, name, path, base_sha):
        # Trusted administrative setup only: intentionally no public path registration API.
        with self.engine.begin() as c:
            c.execute(repositories.insert().values(id=repository_id, tenant_id=tenant_id,
                name=name, path=path, base_sha=base_sha))

    def repository(self, repository_id):
        with self.engine.connect() as c:
            row = c.execute(sa.select(repositories).where(repositories.c.id == repository_id)).mappings().first()
            return dict(row) if row else None

    def enqueue(self, repository_id, head_sha, actor_id, *, rerun_key=None, connection=None, source_context=None):
        from ..engine import _implementation_digest
        implementation_digest = _implementation_digest()
        with (nullcontext(connection) if connection is not None else self.engine.begin()) as c:
            repo = c.execute(sa.select(repositories).where(repositories.c.id == repository_id)
                             .with_for_update()).mappings().one()
            inputs = {"schema_version": 2, "repository_id": repository_id, "base_sha": repo["base_sha"],
                      "head_sha": head_sha, "policy_epoch": repo["policy_epoch"],
                      "implementation_digest": implementation_digest,
                      "profile": "static-verification-v1-no-executor"}
            if source_context is not None:
                inputs["github"] = source_context
            digest = sha256_hex(canonical_json(inputs))
            c.execute(insert(runs).values(id=uid(), repository_id=repository_id, inputs=inputs,
                input_digest=digest).on_conflict_do_nothing(index_elements=["repository_id", "input_digest"]))
            run = c.execute(sa.select(runs).where(runs.c.repository_id == repository_id,
                runs.c.input_digest == digest).with_for_update()).mappings().one()
            key = rerun_key or "initial"
            old = c.execute(sa.select(attempts).where(attempts.c.run_id == run["id"],
                attempts.c.request_key == key)).mappings().first()
            if old:
                return {"run_id": run["id"], "attempt_id": old["id"], "state": old["state"], "duplicate": True}
            aid = uid()
            c.execute(attempts.insert().values(id=aid, run_id=run["id"], request_key=key, requested_by=actor_id))
            previous = None
            for stage in STAGES:
                tid = uid()
                c.execute(tasks.insert().values(id=tid, attempt_id=aid, stage=stage))
                if previous:
                    c.execute(dependencies.insert().values(task_id=tid, depends_on=previous))
                previous = tid
            self._event(c, "ATTEMPT_QUEUED", actor_id, {"run_id": run["id"]}, aid)
            return {"run_id": run["id"], "attempt_id": aid, "state": "queued", "duplicate": False}

    @staticmethod
    def _seconds(seconds):
        if not 1 <= seconds <= 3600:
            raise ValueError("Lease must be between 1 and 3600 seconds")
        return timedelta(seconds=seconds)

    def claim(self, worker_id, lease_seconds=30):
        duration = self._seconds(lease_seconds)
        with self.engine.begin() as c:
            parent = tasks.alias("parent")
            blocked = sa.exists(sa.select(dependencies.c.task_id).join(parent,
                dependencies.c.depends_on == parent.c.id).where(dependencies.c.task_id == tasks.c.id,
                parent.c.state != "succeeded"))
            from .schema_v5 import checks, installations
            revoked = sa.exists(sa.select(checks.c.attempt_id).join(installations,
                installations.c.repository_id == checks.c.repository_id).where(
                checks.c.attempt_id == tasks.c.attempt_id, installations.c.enabled.is_(False)))
            task = c.execute(sa.select(tasks).where(tasks.c.state == "queued", ~revoked,
                tasks.c.available_at <= sa.func.clock_timestamp(), tasks.c.tries < tasks.c.max_tries,
                ~blocked).order_by(tasks.c.created_at, tasks.c.id).with_for_update(skip_locked=True)
                .limit(1)).mappings().first()
            if task is None:
                return None
            row = c.execute(tasks.update().where(tasks.c.id == task["id"]).values(
                state="running", tries=tasks.c.tries + 1, lease_epoch=tasks.c.lease_epoch + 1,
                lease_owner=worker_id, lease_until=sa.func.clock_timestamp() + duration)
                .returning(tasks)).mappings().one()
            c.execute(attempts.update().where(attempts.c.id == task["attempt_id"]).values(state="running"))
            self._event(c, "TASK_CLAIMED", worker_id,
                {"task_id": row["id"], "stage": row["stage"], "epoch": row["lease_epoch"]}, row["attempt_id"])
            return dict(row)

    @staticmethod
    def _lease_where(claim):
        return sa.and_(tasks.c.id == claim["id"], tasks.c.state == "running",
            tasks.c.lease_owner == claim["lease_owner"], tasks.c.lease_epoch == claim["lease_epoch"],
            tasks.c.lease_until > sa.func.clock_timestamp())

    def heartbeat(self, claim, lease_seconds=30):
        with self.engine.begin() as c:
            count = c.execute(tasks.update().where(self._lease_where(claim)).values(
                lease_until=sa.func.clock_timestamp() + self._seconds(lease_seconds))).rowcount
            if count != 1:
                raise LeaseLost("Lease expired or superseded")

    def context(self, claim):
        with self.engine.connect() as c:
            row = c.execute(sa.select(runs.c.inputs, repositories.c.path).select_from(
                attempts.join(runs).join(repositories)).where(attempts.c.id == claim["attempt_id"])).mappings().one()
            outputs = c.execute(sa.select(tasks.c.stage, tasks.c.output).where(
                tasks.c.attempt_id == claim["attempt_id"], tasks.c.state == "succeeded")).all()
            return {"inputs": row["inputs"], "repository_path": row["path"], "outputs": dict(outputs)}

    def complete(self, claim, output):
        if len(canonical_json(output).encode()) > MAX_OUTPUT_BYTES:
            raise ValueError("Task output exceeds limit")
        with self.engine.begin() as c:
            task = c.execute(sa.select(tasks).where(self._lease_where(claim))
                             .with_for_update()).mappings().first()
            if task is None:
                raise LeaseLost("Cannot finalize an expired or superseded lease")
            c.execute(tasks.update().where(tasks.c.id == task["id"]).values(
                state="succeeded", output=output, lease_until=None, lease_owner=None))
            self._event(c, "TASK_COMPLETED", claim["lease_owner"],
                {"task_id": task["id"], "stage": task["stage"], "epoch": task["lease_epoch"]}, task["attempt_id"])
            if task["stage"] == "publish":
                result = c.scalar(sa.select(tasks.c.output).where(tasks.c.attempt_id == task["attempt_id"],
                    tasks.c.stage == "aggregate", tasks.c.state == "succeeded"))
                if result is None:
                    raise RuntimeError("Aggregate evidence is missing")
                c.execute(attempts.update().where(attempts.c.id == task["attempt_id"]).values(
                    state="completed", result=result, finished_at=sa.func.clock_timestamp()))
                c.execute(insert(outbox).values(id=uid(), attempt_id=task["attempt_id"],
                    kind="verification.completed", payload=result).on_conflict_do_nothing(
                    index_elements=["attempt_id", "kind"]))
                self._event(c, "ATTEMPT_COMPLETED", claim["lease_owner"],
                    {"verdict": result["verdict"]}, task["attempt_id"])

    def _retry_or_fail(self, c, task, error, actor):
        retry = task["tries"] < task["max_tries"]
        c.execute(tasks.update().where(tasks.c.id == task["id"]).values(
            state="queued" if retry else "failed", lease_owner=None, lease_until=None, error=error,
            available_at=sa.func.clock_timestamp() + timedelta(seconds=min(30, 2 ** task["tries"]))))
        if not retry:
            c.execute(tasks.update().where(tasks.c.attempt_id == task["attempt_id"],
                tasks.c.state == "queued").values(state="cancelled"))
            c.execute(attempts.update().where(attempts.c.id == task["attempt_id"]).values(
                state="failed-infrastructure", result=None, finished_at=sa.func.clock_timestamp()))
        self._event(c, "TASK_RETRY" if retry else "ATTEMPT_FAILED", actor,
            {"task_id": task["id"], "error": error, "tries": task["tries"]}, task["attempt_id"])

    def fail(self, claim, error_code):
        # Callers supply a bounded error class/code, never exception text containing credentials.
        with self.engine.begin() as c:
            task = c.execute(sa.select(tasks).where(self._lease_where(claim)).with_for_update()).mappings().first()
            if task is None:
                raise LeaseLost("Cannot fail an expired or superseded lease")
            self._retry_or_fail(c, task, error_code[:120], claim["lease_owner"])

    def recover_expired(self):
        # This recovery path is ONLY for the fixed, repeatable verification stages.
        # It never replays action executions or external side effects.
        with self.engine.begin() as c:
            expired = c.execute(sa.select(tasks).where(tasks.c.state == "running",
                tasks.c.lease_until <= sa.func.clock_timestamp()).order_by(tasks.c.id)
                .with_for_update(skip_locked=True).limit(100)).mappings().all()
            for task in expired:
                self._retry_or_fail(c, task, "lease_expired", "recovery")
            return len(expired)

    def get_attempt(self, attempt_id):
        with self.engine.connect() as c:
            row = c.execute(sa.select(attempts, runs.c.repository_id).join(runs).where(
                attempts.c.id == attempt_id)).mappings().first()
            if row is None:
                return None
            result = dict(row)
            result["tasks"] = [dict(x) for x in c.execute(sa.select(tasks.c.id, tasks.c.stage,
                tasks.c.state, tasks.c.tries, tasks.c.error).where(tasks.c.attempt_id == attempt_id)).mappings()]
            return result

    def attempt_events(self, attempt_id):
        with self.engine.connect() as c:
            return [dict(x) for x in c.execute(sa.select(events).where(
                events.c.attempt_id == attempt_id).order_by(events.c.id)).mappings()]

    def create_session(self, repository_id, owner_id, ttl_seconds=3600, action_scope=None):
        sid = uid()
        with self.engine.begin() as c:
            c.execute(sessions.insert().values(id=sid, repository_id=repository_id, owner_id=owner_id,
                expires_at=sa.func.clock_timestamp() + self._seconds(ttl_seconds)))
            self._event(c, "SESSION_CREATED", owner_id, {}, session=sid)
            if action_scope is not None:
                from .schema_v2 import session_scopes
                c.execute(session_scopes.insert().values(session_id=sid, payload=action_scope))
        return sid

    def get_session(self, session_id):
        with self.engine.connect() as c:
            row = c.execute(sa.select(sessions, (sessions.c.expires_at > sa.func.clock_timestamp()).label("unexpired"))
                            .where(sessions.c.id == session_id)).mappings().first()
            return dict(row) if row else None

    def revoke_session(self, session_id, actor_id):
        with self.engine.begin() as c:
            c.execute(sessions.update().where(sessions.c.id == session_id, sessions.c.state == "active").values(
                state="revoked", revocation_epoch=sessions.c.revocation_epoch + 1))
            self._event(c, "SESSION_REVOKED", actor_id, {}, session=session_id)
