"""Trusted snapshot/sign/checkpoint path; read-only replay cannot dispatch execution."""
from pathlib import Path
import sqlalchemy as sa
from fastapi import HTTPException

from ..authorization import load_public_keys
from ..evidence import assemble, redact, digest, verify_bundle, MAX_EVENTS
from .durable import uid
from .schema_v1 import repositories, runs, attempts, tasks, sessions, events, decisions, action_requests, executions
from .schema_v2 import approvals
from .schema_v3 import authorizations
from .schema_v4 import checkpoints
from .signing import DecisionSigner


class EvidenceService:
    def __init__(self, store, cfg):
        self.store, self.cfg = store, cfg

    def access(self, c, kind, subject_id, actor):
        if kind == "attempt":
            subject = c.execute(sa.select(attempts, runs.c.repository_id, runs.c.inputs, runs.c.input_digest)
                .join(runs).where(attempts.c.id == subject_id)).mappings().first()
        elif kind == "session":
            subject = c.execute(sa.select(sessions).where(sessions.c.id == subject_id)).mappings().first()
        else:
            raise HTTPException(404, "evidence subject not found")
        if subject is None:
            raise HTTPException(404, "evidence subject not found")
        repo = c.execute(sa.select(repositories).where(repositories.c.id == subject["repository_id"])).mappings().one()
        if repo["tenant_id"] != actor.tenant_id or repo["id"] not in actor.repository_ids:
            raise HTTPException(404, "evidence subject not found")
        if kind == "session" and subject["owner_id"] != actor.id and actor.role != "administrator":
            raise HTTPException(403, "session belongs to another identity")
        return subject, repo

    def roots(self, c):
        return [*c.scalars(sa.select(repositories.c.path)).all(), str(Path(__file__).resolve().parents[2])]

    def seal(self, kind, subject_id, actor):
        if actor.role not in ("administrator", "reviewer"):
            raise HTTPException(403, "trusted reviewer required to seal evidence")
        if not self.cfg.signing_key_file or not self.cfg.signing_key_id:
            raise HTTPException(501, "evidence signer is not configured")
        # One consistent DB snapshot, including artifacts and all corresponding events.
        with self.store.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
            subject, repo = self.access(c, kind, subject_id, actor)
            context = {"kind": kind, "subject_id": subject_id, "tenant_id": repo["tenant_id"], "repository_id": repo["id"]}
            if kind == "attempt":
                if subject["state"] not in ("completed", "failed-infrastructure", "cancelled"):
                    raise HTTPException(409, "attempt is not terminal")
                if subject["state"] == "completed" and subject["result"] is None:
                    raise HTTPException(409, "completed attempt has no result")
                context.update(run_id=subject["run_id"], input_digest=subject["input_digest"], inputs=subject["inputs"])
                artifacts = {"result": subject["result"], "attempt": dict(subject),
                    "stages": [dict(r) for r in c.execute(sa.select(tasks.c.id, tasks.c.stage, tasks.c.state,
                        tasks.c.output, tasks.c.error).where(tasks.c.attempt_id == subject_id).order_by(tasks.c.stage)).mappings()]}
                predicate = events.c.attempt_id == subject_id
            else:
                artifacts = {"session": dict(subject)}
                requests = sa.select(action_requests.c.id).where(action_requests.c.session_id == subject_id)
                decision_ids = sa.select(decisions.c.id).where(decisions.c.action_request_id.in_(requests))
                for name, table, predicate in (
                    ("requests", action_requests, action_requests.c.session_id == subject_id),
                    ("decisions", decisions, decisions.c.action_request_id.in_(requests)),
                    ("approvals", approvals, approvals.c.decision_id.in_(decision_ids)),
                    ("executions", executions, executions.c.decision_id.in_(decision_ids))):
                    rows = c.execute(sa.select(table).where(predicate).order_by(list(table.primary_key)[0]).limit(MAX_EVENTS + 1)).mappings().all()
                    if len(rows) > MAX_EVENTS:
                        raise HTTPException(413, "evidence history limit exceeded")
                    artifacts[name] = [dict(r) for r in rows]
                # Preserve the exact issued execution context without exporting its
                # reusable bearer signature. The original action hash survives redaction.
                issued = c.execute(sa.select(authorizations.c.decision_id,
                    authorizations.c.token["payload"].label("context"))
                    .where(authorizations.c.decision_id.in_(decision_ids))
                    .order_by(authorizations.c.decision_id).limit(MAX_EVENTS + 1)).mappings().all()
                if len(issued) > MAX_EVENTS:
                    raise HTTPException(413, "evidence history limit exceeded")
                artifacts["authorization_contexts"] = [dict(r) for r in issued]
                predicate = events.c.session_id == subject_id
            history = [dict(r) for r in c.execute(sa.select(events).where(predicate).order_by(events.c.id).limit(MAX_EVENTS + 1)).mappings()]
            try:
                bundle = assemble(context, redact(artifacts), redact(history))
                signer = DecisionSigner(self.cfg.signing_key_file, self.cfg.signing_key_id, self.roots(c))
                bundle = signer.sign_evidence(bundle)
                # Configuration mistakes must not persist an unverifiable checkpoint.
                keys = load_public_keys(self.cfg.verification_keys_file, self.roots(c))
                manifest = bundle["manifest"]
                row = {"id": uid(), "kind": kind, "subject_id": subject_id, "context": context,
                       "bundle_digest": digest(bundle), "event_count": manifest["event_count"],
                       "event_head": manifest["event_head"], "bundle": bundle}
                verify_bundle(bundle, keys, row, context)
            except (ValueError, OSError, TypeError):
                raise HTTPException(503, "evidence signing or validation failed") from None
            c.execute(checkpoints.insert().values(**row))
            return {"checkpoint_id": row["id"], "bundle": bundle}

    def replay(self, checkpoint_id, actor, bundle=None):
        with self.store.engine.connect() as c:
            row = c.execute(sa.select(checkpoints).where(checkpoints.c.id == checkpoint_id)).mappings().first()
            if row is None:
                raise HTTPException(404, "checkpoint not found")
            self.access(c, row["kind"], row["subject_id"], actor)
            try:
                keys = load_public_keys(self.cfg.verification_keys_file, self.roots(c))
                replay = verify_bundle(row["bundle"] if bundle is None else bundle, keys, row, row["context"])
            except (ValueError, OSError, TypeError):
                raise HTTPException(409, "evidence authentication failed") from None
            return {"checkpoint_id": checkpoint_id, **replay}

    def cache_eligibility(self, checkpoint_id, actor, expected_inputs):
        """Eligibility is not reuse: legacy filesystem caches remain disabled.

        Only authenticated, exact-context static results requiring no tests can
        qualify. Dynamic test reuse is closed until validated worker integration.
        """
        replay = self.replay(checkpoint_id, actor)
        context, artifacts = replay["context"], replay["artifacts"]
        eligible, reason = False, "context or required evidence does not qualify"
        if context["kind"] == "attempt":
            from ..engine import _implementation_digest
            with self.store.engine.connect() as c:
                _, repo = self.access(c, "attempt", context["subject_id"], actor)
            result = artifacts.get("result") or {}
            inputs = context["inputs"]
            if (not isinstance(result, dict) or any(not isinstance(result.get(k), dict)
                    for k in ("plan", "tests", "execution_availability"))
                    or not isinstance(result.get("findings"), list)
                    or any(not isinstance(f, dict) for f in result["findings"])):
                return {"authenticated": True, "cache_eligible": False, "reason": reason,
                        "reuse_enabled": False, "checkpoint_id": checkpoint_id}
            eligible = (expected_inputs == inputs and digest(inputs) == context["input_digest"]
                and inputs.get("policy_epoch") == repo["policy_epoch"]
                and inputs.get("base_sha") == repo["base_sha"]
                and inputs.get("implementation_digest") == _implementation_digest()
                and inputs.get("profile") == "static-verification-v1-no-executor"
                and {s["stage"] for s in artifacts["stages"]} == {"snapshot", "analyze", "tests", "aggregate", "publish"}
                and all(s["state"] == "succeeded" for s in artifacts["stages"])
                and artifacts["attempt"]["state"] == "completed" and result.get("verdict") == "PASS"
                and result.get("plan", {}).get("mode") == "NONE"
                # The static analyzer records NOT_RUN even for a NONE plan; the
                # independent tests stage must explicitly establish NOT_NEEDED.
                and result.get("tests", {}).get("status") in ("NOT_RUN", "NOT_NEEDED")
                and result.get("execution_availability", {}).get("status") == "NOT_NEEDED"
                and all(f.get("status") == "PASS" for f in result.get("findings", [])
                        if f.get("rule_type") == "required_test"))
            if eligible: reason = "authenticated exact-context static evidence; no tests required"
        return {"authenticated": True, "cache_eligible": eligible, "reason": reason,
                "reuse_enabled": False, "checkpoint_id": checkpoint_id}
