import copy
import json

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from reposhield.evidence import verify_bundle, digest, redact, MAX_BUNDLE
from reposhield.server.evidence_service import EvidenceService
from reposhield.server.config import ServerConfig
from reposhield.server.schema_v1 import attempts, executions, events
from reposhield.server.schema_v4 import checkpoints
from reposhield.server.execution_service import ExecutionService
from reposhield.server.process_worker import ProcessWorker
from reposhield.gitutil import resolve
from tests.test_authorization import signed, service, pg, registered, actor, executor, claim


@pytest.fixture
def evidence(signed, demo_repo):
    f = signed
    store = f["policy"].store
    cfg = ServerConfig(signing_key_file=str(f["private_path"]), signing_key_id="test-key",
                       verification_keys_file=str(f["public_path"]))
    svc = EvidenceService(store, cfg)
    job = store.enqueue("repo", resolve(demo_repo, "pr/docs-only"), "agent")
    # Synthetic persisted result for integrity unit/integration tests. Real worker test below.
    with store.engine.begin() as c:
        c.execute(attempts.update().where(attempts.c.id == job["attempt_id"]).values(state="completed",
            result={"verdict": "REVIEW_REQUIRED", "tests": {"status": "NOT_RUN"}, "stdout": "password=never-retain"}))
        store._event(c, "ATTEMPT_COMPLETED", "test", {"verdict": "REVIEW_REQUIRED"}, job["attempt_id"])
    admin = actor("administrator", "administrator")
    sealed = svc.seal("attempt", job["attempt_id"], admin)
    with store.engine.connect() as c:
        checkpoint = dict(c.execute(sa.select(checkpoints).where(checkpoints.c.id == sealed["checkpoint_id"])).mappings().one())
    return dict(f=f, service=svc, admin=admin, sealed=sealed, checkpoint=checkpoint, job=job)


def test_authenticated_replay_is_read_only_redacted_and_not_pass(evidence):
    x = evidence
    before = x["f"]["policy"].store.get_attempt(x["job"]["attempt_id"])
    replay = x["service"].replay(x["sealed"]["checkpoint_id"], actor("viewer", "viewer"))
    assert replay["authenticated"] and replay["cache_eligible"] is False
    assert replay["artifacts"]["result"]["verdict"] == "REVIEW_REQUIRED"
    assert replay["artifacts"]["result"]["stdout"] == "[OMITTED]"
    assert "never-retain" not in json.dumps(replay)
    assert before == x["f"]["policy"].store.get_attempt(x["job"]["attempt_id"])


@pytest.mark.parametrize("tamper", ["result", "artifact_delete", "artifact_add", "truncate", "reorder", "event",
    "head", "count", "signature", "key", "tenant", "run", "attempt", "inputs", "oversized"])
def test_altered_bundle_never_authenticates(evidence, tamper):
    x = evidence
    bundle = copy.deepcopy(x["sealed"]["bundle"])
    if tamper == "result": bundle["artifacts"]["result"]["verdict"] = "PASS"
    if tamper == "artifact_delete": del bundle["artifacts"]["result"]
    if tamper == "artifact_add": bundle["artifacts"]["extra"] = "injected"
    if tamper == "truncate": bundle["events"].pop()
    if tamper == "reorder": bundle["events"].reverse()
    if tamper == "event": bundle["events"][0]["entry"]["kind"] = "FORGED"
    if tamper == "head": bundle["manifest"]["event_head"] = "0" * 64
    if tamper == "count": bundle["manifest"]["event_count"] -= 1
    if tamper == "signature": bundle["signature"] = "A" * 88
    if tamper == "key": bundle["key_id"] = "unknown"
    if tamper == "tenant": bundle["manifest"]["context"]["tenant_id"] = "other"
    if tamper == "run": bundle["manifest"]["context"]["run_id"] = "other"
    if tamper == "attempt": bundle["manifest"]["context"]["subject_id"] = "other"
    if tamper == "inputs": bundle["manifest"]["context"]["inputs"]["policy_epoch"] += 1
    if tamper == "oversized": bundle["artifacts"]["extra"] = "x" * MAX_BUNDLE
    with pytest.raises(HTTPException) as error:
        x["service"].replay(x["sealed"]["checkpoint_id"], x["admin"], bundle)
    assert error.value.status_code == 409


def test_untrusted_recomputed_checkpoint_and_wrong_context_are_rejected(evidence):
    x = evidence
    bundle = x["sealed"]["bundle"]
    for field in ("tenant_id", "repository_id", "run_id", "subject_id", "input_digest"):
        context = {**x["checkpoint"]["context"], field: "other"}
        with pytest.raises(ValueError):
            verify_bundle(bundle, x["f"]["keys"], x["checkpoint"], context)
    with pytest.raises(ValueError):
        verify_bundle(bundle, {"test-key": Ed25519PrivateKey.generate().public_key()}, x["checkpoint"], x["checkpoint"]["context"])
    changed = {**x["checkpoint"], "event_head": "f" * 64}
    with pytest.raises(ValueError):
        verify_bundle(bundle, x["f"]["keys"], changed, x["checkpoint"]["context"])


def test_cross_checkpoint_copy_and_database_mutation_denied(evidence):
    x = evidence
    sid = x["f"]["body"].session_id
    other = x["service"].seal("session", sid, x["admin"])
    with pytest.raises(HTTPException):
        x["service"].replay(other["checkpoint_id"], x["admin"], x["sealed"]["bundle"])
    for statement in (checkpoints.update().values(event_head="f"*64).where(checkpoints.c.id == x["sealed"]["checkpoint_id"]),
                      checkpoints.delete().where(checkpoints.c.id == x["sealed"]["checkpoint_id"]),
                      sa.text("TRUNCATE evidence_checkpoints")):
        with pytest.raises(sa.exc.DBAPIError, match="immutable"):
            with x["f"]["policy"].store.engine.begin() as c:
                c.execute(statement)
    assert x["service"].replay(x["sealed"]["checkpoint_id"], x["admin"])["authenticated"]


def test_valid_resign_cannot_replace_trusted_checkpoint(evidence):
    from reposhield.server.signing import DecisionSigner
    from reposhield.evidence import assemble
    x = evidence
    old = x["sealed"]["bundle"]
    changed = copy.deepcopy(old["artifacts"])
    changed["result"]["verdict"] = "PASS"
    replacement = assemble(old["manifest"]["context"], changed, [r["entry"] for r in old["events"][:-1]])
    replacement = DecisionSigner(x["f"]["private_path"], "test-key", []).sign_evidence(replacement)
    with pytest.raises(HTTPException) as error:
        x["service"].replay(x["sealed"]["checkpoint_id"], x["admin"], replacement)
    assert error.value.status_code == 409


def test_removed_verification_key_revokes_evidence_eligibility(evidence):
    x = evidence
    path = x["f"]["public_path"]
    original = path.read_bytes()
    try:
        path.write_text("{}")
        with pytest.raises(HTTPException):
            x["service"].cache_eligibility(x["sealed"]["checkpoint_id"], x["admin"], x["checkpoint"]["context"]["inputs"])
    finally:
        path.write_bytes(original)


def test_missing_evidence_keys_and_unauthorized_subjects_fail_closed(evidence):
    x = evidence
    for role in ("agent", "viewer"):
        with pytest.raises(HTTPException) as error:
            x["service"].seal("attempt", x["job"]["attempt_id"], actor(role, role))
        assert error.value.status_code == 403
    for identity in (actor().model_copy(update={"tenant_id": "other"}), actor().model_copy(update={"repository_ids": ["other"]})):
        with pytest.raises(HTTPException) as error:
            x["service"].replay(x["sealed"]["checkpoint_id"], identity)
        assert error.value.status_code == 404
    x["service"].cfg.verification_keys_file = None
    with pytest.raises(HTTPException):
        x["service"].replay(x["sealed"]["checkpoint_id"], x["admin"])


def test_session_history_includes_decision_claim_finish_revoke_without_secrets(evidence):
    x, f = evidence, evidence["f"]
    execution = claim(f)
    outcome = {"stdout": "credential=do-not-retain", "junit": "secret=do-not-retain", "password": "hidden",
               "note": "Bearer abc123 password=hidden postgresql://user:password@host/db"}
    lifecycle = ExecutionService(f["policy"])
    lifecycle.finish(execution["execution_id"], executor(), "completed", outcome)
    # Idempotency remains defined over the retained representation.
    lifecycle.finish(execution["execution_id"], executor(), "completed", outcome)
    with f["policy"].store.engine.connect() as c:
        stored = c.scalar(sa.select(executions.c.outcome).where(executions.c.id == execution["execution_id"]))
    assert "do-not-retain" not in json.dumps(stored) and "abc123" not in json.dumps(stored)
    sid = f["body"].session_id
    f["policy"].store.revoke_session(sid, "agent")
    sealed = x["service"].seal("session", sid, x["admin"])
    replay = x["service"].replay(sealed["checkpoint_id"], x["admin"])
    kinds = {r["kind"] for r in replay["history"]}
    assert {"SESSION_CREATED", "ACTION_DECIDED", "EXECUTION_FINISHED", "SESSION_REVOKED"} <= kinds
    assert replay["artifacts"]["executions"][0]["state"] == "completed"
    issued = replay["artifacts"]["authorization_contexts"][0]["context"]
    assert issued["profile"] == f["token"]["payload"]["profile"]
    assert issued["request"]["workspace_revision"] == f["body"].workspace_revision
    assert "signature" not in json.dumps(replay["artifacts"]["authorization_contexts"])
    assert replay["cache_eligible"] is False
    assert not x["service"].cache_eligibility(sealed["checkpoint_id"], x["admin"], {})["cache_eligible"]


def test_real_worker_result_can_be_sealed_without_rerunning(evidence, demo_repo):
    x = evidence
    store = x["f"]["policy"].store
    # Cancel synthetic fixture tasks so the worker only processes the real fresh attempt.
    from reposhield.server.schema_v1 import tasks
    with store.engine.begin() as c:
        c.execute(tasks.update().where(tasks.c.attempt_id == x["job"]["attempt_id"]).values(state="cancelled"))
    job = store.enqueue("repo", resolve(demo_repo, "pr/docs-only"), "agent", rerun_key="real-worker")
    worker = ProcessWorker(store)
    for _ in range(5): assert worker.run_once()
    result = store.get_attempt(job["attempt_id"])
    assert result["state"] == "completed"
    sealed = x["service"].seal("attempt", job["attempt_id"], x["admin"])
    replay = x["service"].replay(sealed["checkpoint_id"], x["admin"])
    assert replay["artifacts"]["result"]["verdict"] == result["result"]["verdict"]
    assert not replay["cache_eligible"]
    inputs = replay["context"]["inputs"]
    eligible = x["service"].cache_eligibility(sealed["checkpoint_id"], x["admin"], inputs)
    assert eligible["cache_eligible"] and not eligible["reuse_enabled"]
    for field in ("head_sha", "base_sha", "implementation_digest", "policy_epoch", "profile"):
        wrong = {**inputs, field: "other"}
        assert not x["service"].cache_eligibility(sealed["checkpoint_id"], x["admin"], wrong)["cache_eligible"]
    from reposhield.server.schema_v1 import repositories
    with store.engine.begin() as c:
        c.execute(repositories.update().where(repositories.c.id == "repo").values(policy_epoch=2))
    assert not x["service"].cache_eligibility(sealed["checkpoint_id"], x["admin"], inputs)["cache_eligible"]


def test_api_scopes_and_real_replay_routes(evidence, pg):
    from reposhield.server.app import create_app
    import hashlib
    x = evidence
    identities = [actor(name, name).model_copy(update={"token_sha256": hashlib.sha256(name.encode()).hexdigest()}).model_dump(mode="json")
                  for name in ("administrator", "viewer", "agent")]
    path = x["f"]["private_path"].parent / "evidence-users.json"
    path.write_text(json.dumps(identities))
    cfg = x["service"].cfg
    cfg.database_url, cfg.identities_file = pg[1], str(path)
    cid = x["sealed"]["checkpoint_id"]
    with TestClient(create_app(cfg)) as client:
        headers = {"Authorization": "Bearer administrator"}
        assert client.get(f"/api/v1/evidence/{cid}").status_code == 401
        assert client.get(f"/api/v1/evidence/{cid}", headers=headers).json()["authenticated"]
        assert client.post(f"/api/v1/evidence/{cid}/verify", headers=headers, json=x["sealed"]["bundle"]).status_code == 200
        assert client.post(f"/api/v1/evidence/{cid}/verify", headers=headers, json={}).status_code == 409
        assert not client.post(f"/api/v1/evidence/{cid}/cache-eligibility", headers=headers, json={}).json()["cache_eligible"]
        route = f"/api/v1/evidence/attempt/{x['job']['attempt_id']}/seal"
        for name in ("agent", "viewer"):
            assert client.post(route, headers={"Authorization": "Bearer " + name}).status_code == 403
        assert client.post(route, headers=headers).status_code == 200


def test_incomplete_attempt_missing_history_and_wrong_key_cannot_checkpoint(evidence):
    x = evidence
    store, aid = x["f"]["policy"].store, x["job"]["attempt_id"]
    with store.engine.begin() as c:
        c.execute(attempts.update().where(attempts.c.id == aid).values(state="running"))
    with pytest.raises(HTTPException) as error:
        x["service"].seal("attempt", aid, x["admin"])
    assert error.value.status_code == 409
    with store.engine.begin() as c:
        c.execute(attempts.update().where(attempts.c.id == aid).values(state="completed", result=None))
    with pytest.raises(HTTPException): x["service"].seal("attempt", aid, x["admin"])
    with store.engine.begin() as c:
        c.execute(attempts.update().where(attempts.c.id == aid).values(result={"verdict": "REVIEW_REQUIRED"}))
        c.execute(events.delete().where(events.c.attempt_id == aid))
    with pytest.raises(HTTPException): x["service"].seal("attempt", aid, x["admin"])
    # Historical sealed bundle remains verifiable independently of mutable live tables.
    assert x["service"].replay(x["sealed"]["checkpoint_id"], x["admin"])["authenticated"]
    with store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(checkpoints)) == 1


def test_log_redaction_and_bounds():
    value = redact({"stdout": "untrusted log", "client_secret": "secret", "note": "x" * 10000,
                    "key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"})
    assert value["stdout"] == value["client_secret"] == "[OMITTED]"
    assert len(value["note"]) < 4200 and value["key"] == "[REDACTED KEY]"
    nested = {}
    for _ in range(35): nested = {"nest": nested}
    with pytest.raises(ValueError): redact(nested)
