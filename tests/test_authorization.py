import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient
import hashlib

from reposhield.authorization import ExecutionProfile, verify_token, load_public_keys
from reposhield.server.authorization_service import IssuanceService, ClaimService
from reposhield.server.signing import DecisionSigner
from reposhield.server.identities import ExecutorIdentity
from reposhield.server.schema_v1 import executions, decisions, sessions, events, repositories
from reposhield.server.schema_v3 import authorizations
from reposhield.server.config import ServerConfig
from reposhield.server.app import create_app
from tests.test_action_policy import service, request, patch, actor, pg, registered

PROFILE = dict(image="python@sha256:" + "b"*64, executor_audience="broker",
               timeout_seconds=30, memory_mb=256, cpu_millis=1000, pids=32,
               disk_mb=64, output_bytes=65536, uid=1000)


def executor(**kw):
    return ExecutorIdentity(id="broker", tenant_id="tenant", repository_ids=["repo"],
                            token_sha256="1"*64).model_copy(update=kw)


@pytest.fixture
def signed(service):
    svc, sid, policy_path = service
    config = json.loads(policy_path.read_text())
    config["resources"][0].update(default_profile="isolated-python", execution_profiles={"isolated-python": PROFILE})
    policy_path.write_text(json.dumps(config))
    # Test-only ephemeral keys live outside the source tree and candidate repository.
    with tempfile.TemporaryDirectory(prefix="reposhield-signing-test-") as external:
        path = Path(external) / "private.pem"
        key = Ed25519PrivateKey.generate()
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        public_path = Path(external) / "public.json"
        public_path.write_text(json.dumps({"test-key": base64.b64encode(key.public_key().public_bytes_raw()).decode()}))
        issuer = IssuanceService(svc, str(path), "test-key")
        keys = load_public_keys(public_path, [str(Path.cwd())])
        claimer = ClaimService(svc, keys)
        body = request(patch(), sid)
        decision = svc.authorize(body, actor())
        token = issuer.issue(decision["id"], actor())
        yield dict(policy=svc, issuer=issuer, claimer=claimer, body=body, token=token, keys=keys,
                   policy_path=policy_path, private_path=path, public_path=public_path, key=key)


def claim(f, token=None, **kw):
    return f["claimer"].claim(token or f["token"], kw.get("body", f["body"]), kw.get("resource", "source"),
                               kw.get("profile", ExecutionProfile(**PROFILE)), kw.get("executor", executor()))


def test_real_signature_idempotent_issue_and_one_shot_claim(signed):
    f = signed
    token = f["token"]
    verified = verify_token(token, f["keys"], audience="broker", now=token["payload"]["issued_at"])
    assert verified.payload.request == f["body"]
    assert f["issuer"].issue(token["payload"]["decision_id"], actor()) == token
    result = claim(f)
    assert result["state"] == "unknown-outcome" and not result["execution_enabled"]
    with pytest.raises(HTTPException) as exc:
        claim(f)
    assert exc.value.status_code == 409
    with f["policy"].store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(executions)) == 1


@pytest.mark.parametrize("field,value", [
    ("requested_by", "attacker"), ("resource_id", "production"), ("nonce", "f"*32),
    ("policy_digest", "f"*64), ("policy_epoch", 2), ("revocation_epoch", 1),
    ("profile_name", "host"), ("decision_id", "f"*32), ("approval_digest", "f"*64),
    ("expires_at", 1), ("issued_at", 1)])
def test_signed_fields_cannot_be_changed(signed, field, value):
    token = copy.deepcopy(signed["token"])
    token["payload"][field] = value
    with pytest.raises(HTTPException) as exc:
        claim(signed, token)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("kind", ["path", "snapshot", "session", "tenant", "repo", "image", "limits", "audience", "key", "algorithm", "version", "signature"])
def test_nested_or_envelope_tampering_denied(signed, kind):
    token = copy.deepcopy(signed["token"])
    p = token["payload"]
    if kind == "path":
        p["request"]["action"]["patch"] = patch("docs/guide.md")["patch"]
    elif kind in ("snapshot", "session", "tenant", "repo"):
        key = {"snapshot": "workspace_revision", "session": "session_id", "tenant": "tenant_id", "repo": "repository_id"}[kind]
        p["request"][key] = "sha256:" + "f"*64 if kind == "snapshot" else "other"
    elif kind in ("image", "limits", "audience"):
        key = {"image": "image", "limits": "timeout_seconds", "audience": "executor_audience"}[kind]
        p["profile"][key] = {"image": "python@sha256:" + "f"*64, "limits": 31, "audience": "other"}[kind]
    else:
        key = {"key": "key_id", "algorithm": "algorithm", "version": "version", "signature": "signature"}[kind]
        token[key] = {"key": "other", "algorithm": "HS256", "version": 2, "signature": "A"*86}[kind]
    with pytest.raises(HTTPException) as exc:
        claim(signed, token)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("kind", ["resource", "session", "profile", "audience", "tenant", "repository", "role"])
def test_valid_token_cannot_authorize_a_different_execution_context(signed, kind):
    kw = {}
    if kind == "resource":
        kw["resource"] = "other"
    elif kind == "session":
        kw["body"] = signed["body"].model_copy(update={"session_id": "other"})
    elif kind == "profile":
        kw["profile"] = ExecutionProfile(**{**PROFILE, "memory_mb": 512})
    else:
        attr = {"audience": "id", "tenant": "tenant_id", "repository": "repository_ids", "role": "role"}[kind]
        kw["executor"] = executor(**{attr: ["other"] if kind == "repository" else "other"})
    with pytest.raises(HTTPException) as exc:
        claim(signed, **kw)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("change", ["snapshot", "resource", "policy", "image", "limits", "epoch", "revoked", "expired"])
def test_live_context_changes_invalidate_issued_tokens(signed, change):
    f = signed
    if change in ("epoch", "revoked", "expired"):
        with f["policy"].store.engine.begin() as c:
            if change == "epoch":
                c.execute(repositories.update().values(policy_epoch=2))
            elif change == "revoked":
                c.execute(sessions.update().values(state="revoked", revocation_epoch=1))
            else:
                c.execute(decisions.update().values(expires_at=sa.func.clock_timestamp()))
    else:
        config = json.loads(f["policy_path"].read_text())
        r = config["resources"][0]
        if change == "snapshot": r["workspace_revision"] = "sha256:" + "f"*64
        elif change == "resource": r["resource_id"] = "other"
        elif change == "policy": r["administrator"]["actions"] = []
        elif change == "image": r["execution_profiles"]["isolated-python"]["image"] = "python@sha256:" + "f"*64
        else: r["execution_profiles"]["isolated-python"]["timeout_seconds"] = 31
        f["policy_path"].write_text(json.dumps(config))
    with pytest.raises(HTTPException) as exc:
        claim(f)
    assert exc.value.status_code in (403, 409)
    with f["policy"].store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(executions)) == 0


def test_expiry_and_removed_public_key_fail_verification(signed):
    f = signed
    for keys, now in [(f["keys"], f["token"]["payload"]["expires_at"]),
                      (f["keys"], f["token"]["payload"]["issued_at"] - 1),
                      ({}, f["token"]["payload"]["issued_at"])]:
        with pytest.raises(ValueError):
            verify_token(f["token"], keys, audience="broker", now=now)


def test_review_requires_approval_and_binds_it(signed):
    f = signed
    body = request(patch("docs/guide.md"), f["body"].session_id)
    result = f["policy"].authorize(body, actor())
    with pytest.raises(HTTPException) as exc:
        f["issuer"].issue(result["id"], actor())
    assert exc.value.status_code == 409
    f["policy"].approve(result["id"], actor("reviewer"))
    token = f["issuer"].issue(result["id"], actor())
    assert token["payload"]["approval_digest"]
    assert claim(f, token, body=body)["state"] == "unknown-outcome"


def test_denied_decision_never_gets_signed(signed):
    f = signed
    body = request({"action_type": "DATABASE_OPERATION", "resource_id": "prod"}, f["body"].session_id)
    decision = f["policy"].authorize(body, actor())
    with pytest.raises(HTTPException) as exc:
        f["issuer"].issue(decision["id"], actor())
    assert exc.value.status_code == 409


def test_claim_event_failure_rolls_back_nonce_consumption(signed, monkeypatch):
    f = signed
    with monkeypatch.context() as m:
        def fail(*args, **kwargs): raise RuntimeError("injected")
        m.setattr(f["policy"].store, "_event", fail)
        with pytest.raises(RuntimeError): claim(f)
    assert claim(f)["state"] == "unknown-outcome"


def test_concurrent_claims_exactly_one_winner(signed):
    def run(_):
        try: return claim(signed)["state"]
        except HTTPException as e: return e.status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert results.count("unknown-outcome") == 1 and results.count(409) == 3


def test_key_location_missing_signer_and_public_only_verifier(signed, tmp_path, demo_repo):
    f = signed
    with pytest.raises(ValueError):
        DecisionSigner(f["private_path"], "test-key", [str(f["private_path"].parent)])
    with pytest.raises(HTTPException) as exc:
        IssuanceService(f["policy"], None, None).issue(f["token"]["payload"]["decision_id"], actor())
    assert exc.value.status_code == 501
    # Removing the private file cannot affect verification/claiming.
    f["private_path"].unlink()
    assert claim(f)["state"] == "unknown-outcome"


CHILD = r'''
import json,os,sys,time
from pathlib import Path
from fastapi import HTTPException
from reposhield.authorization import ExecutionProfile,load_public_keys
from reposhield.contracts import ActionRequest
from reposhield.server.durable import DurableStore
from reposhield.server.action_service import ActionService
from reposhield.server.authorization_service import ClaimService
from reposhield.server.identities import ExecutorIdentity
data=json.loads(Path(sys.argv[1]).read_text())
store=DurableStore(data['url'])
policy=ActionService(store,data['policy'])
service=ClaimService(policy,load_public_keys(data['public'],[str(Path.cwd())]))
assert 'reposhield.server.signing' not in sys.modules
while not Path(data['start']).exists(): time.sleep(0.02)
try:
    service.claim(data['token'],ActionRequest.model_validate(data['request']), 'source',
                  ExecutionProfile.model_validate(data['profile']),ExecutorIdentity.model_validate(data['executor']))
except HTTPException as e:
    sys.exit(17 if e.status_code==409 else 18)
os._exit(23 if data['crash'] else 0)
'''


@pytest.mark.parametrize("crash", [False, True])
def test_process_replay_and_crash_after_committed_claim(signed, pg, crash):
    f = signed
    directory = f["public_path"].parent
    start = directory / "start"
    data = dict(url=pg[1], policy=str(f["policy_path"]), public=str(f["public_path"]),
                token=f["token"], request=f["body"].model_dump(mode="json"), profile=PROFILE,
                executor=executor().model_dump(mode="json"), start=str(start), crash=crash)
    input_file = directory / "claim.json"
    input_file.write_text(json.dumps(data))
    processes = [subprocess.Popen([sys.executable, "-c", CHILD, str(input_file)]) for _ in range(1 if crash else 2)]
    try:
        start.touch()
        assert sorted(p.wait(timeout=30) for p in processes) == ([23] if crash else [0, 17])
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=5)
    # Restarted claim service still sees permanent consumption, never a retry job.
    from reposhield.server.durable import DurableStore
    restarted = DurableStore(pg[1])
    try:
        assert restarted.recover_expired() == 0
        with restarted.engine.connect() as c:
            rows = c.execute(sa.select(executions)).mappings().all()
            assert len(rows) == 1 and rows[0]["state"] == "unknown-outcome"
        with pytest.raises(HTTPException) as exc: claim(f)
        assert exc.value.status_code == 409
    finally:
        restarted.engine.dispose()


def test_approval_removal_after_issuance_denies_claim(signed):
    from reposhield.server.schema_v2 import approvals
    f = signed
    body = request(patch("docs/guide.md"), f["body"].session_id)
    result = f["policy"].authorize(body, actor())
    f["policy"].approve(result["id"], actor("reviewer"))
    token = f["issuer"].issue(result["id"], actor())
    with f["policy"].store.engine.begin() as c:
        c.execute(approvals.delete().where(approvals.c.decision_id == result["id"]))
    with pytest.raises(HTTPException) as exc: claim(f, token, body=body)
    assert exc.value.status_code == 409


def test_http_separate_executor_credentials_and_bound_claim(signed, pg):
    f = signed
    directory = f["public_path"].parent
    users = directory / "users.json"
    brokers = directory / "brokers.json"
    users.write_text(json.dumps([actor().model_copy(update={"token_sha256": hashlib.sha256(b"agent-test").hexdigest()})
                                .model_dump(mode="json")]))
    brokers.write_text(json.dumps([executor(token_sha256=hashlib.sha256(b"broker-test").hexdigest()).model_dump(mode="json")]))
    cfg = ServerConfig(database_url=pg[1], identities_file=str(users), executor_identities_file=str(brokers),
                       signing_key_file=str(f["private_path"]), signing_key_id="test-key",
                       verification_keys_file=str(f["public_path"]), action_policy_file=str(f["policy_path"]))
    with TestClient(create_app(cfg)) as client:
        agent_header = {"Authorization": "Bearer agent-test"}
        broker_header = {"Authorization": "Bearer broker-test"}
        token_route = "/api/v1/actions/" + f["token"]["payload"]["decision_id"] + "/token"
        assert client.post(token_route).status_code == 401
        assert client.post(token_route, headers=broker_header).status_code == 401
        assert client.post(token_route, headers=agent_header).json() == f["token"]
        payload = dict(authorization=f["token"], request=f["body"].model_dump(mode="json"),
                       resource_id="source", profile=PROFILE)
        route = "/api/v1/actions/claim"
        assert client.post(route, json=payload).status_code == 401
        assert client.post(route, json=payload, headers=agent_header).status_code == 401
        assert client.post(route, json={**payload, "resource_id": "other"}, headers=broker_header).status_code == 403
        result = client.post(route, json=payload, headers=broker_header)
        assert result.status_code == 200 and result.json()["state"] == "unknown-outcome"
        assert client.post(route, json=payload, headers=broker_header).status_code == 409
        assert client.post("/api/v1/actions/execute", headers=agent_header).status_code == 501


def test_wrong_public_key_cannot_verify(signed):
    f = signed
    f["claimer"] = ClaimService(f["policy"], {"test-key": Ed25519PrivateKey.generate().public_key()})
    with pytest.raises(HTTPException) as exc: claim(f)
    assert exc.value.status_code == 403


def test_concurrent_issuance_has_one_nonce(signed):
    f = signed
    decision = f["policy"].authorize(f["body"], actor())
    with ThreadPoolExecutor(max_workers=3) as pool:
        tokens = list(pool.map(lambda _: f["issuer"].issue(decision["id"], actor()), range(3)))
    assert tokens[0] == tokens[1] == tokens[2]
    with f["policy"].store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(authorizations)
                        .where(authorizations.c.decision_id == decision["id"])) == 1


def test_missing_profile_and_wrong_requester_cannot_issue(signed):
    f = signed
    with pytest.raises(HTTPException) as exc:
        f["issuer"].issue(f["token"]["payload"]["decision_id"], actor("reviewer"))
    assert exc.value.status_code == 403
    config = json.loads(f["policy_path"].read_text())
    config["resources"][0]["execution_profiles"] = {}
    f["policy_path"].write_text(json.dumps(config))
    decision = f["policy"].authorize(f["body"], actor())
    with pytest.raises(HTTPException) as exc:
        f["issuer"].issue(decision["id"], actor())
    assert exc.value.status_code == 409


def test_issuance_failure_rolls_back_token_nonce_and_event(signed, monkeypatch):
    f = signed
    decision = f["policy"].authorize(f["body"], actor())
    def fail(*args, **kwargs): raise RuntimeError("injected")
    with monkeypatch.context() as m:
        m.setattr(f["policy"].store, "_event", fail)
        with pytest.raises(RuntimeError): f["issuer"].issue(decision["id"], actor())
    with f["policy"].store.engine.connect() as c:
        assert c.scalar(sa.select(decisions.c.nonce).where(decisions.c.id == decision["id"])) is None
        assert c.scalar(sa.select(authorizations.c.token).where(authorizations.c.decision_id == decision["id"])) is None
    assert f["issuer"].issue(decision["id"], actor())["payload"]["nonce"]


@pytest.mark.parametrize("field,value", [("image", "python:latest"), ("network", "allow"), ("uid", 0),
                                         ("read_only_root", False), ("timeout_seconds", 0)])
def test_unsafe_execution_profiles_fail_validation(field, value):
    with pytest.raises(ValueError):
        ExecutionProfile(**{**PROFILE, field: value})
