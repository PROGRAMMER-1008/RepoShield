import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import pytest
import sqlalchemy as sa
import uvicorn
from fastapi import HTTPException

from reposhield.snapshots import SnapshotStore
from reposhield.broker import CoordinatorClient, Broker
from reposhield.restricted_runner import RestrictedRunner
from reposhield.server.app import create_app
from reposhield.server.config import ServerConfig
from reposhield.server.execution_service import ExecutionService
from reposhield.server.schema_v1 import executions
from tests.test_authorization import signed, service, pg, registered, actor, executor, request, patch
from tests.test_restricted_execution import profile


@pytest.fixture
def connected(signed, pg):
    f = signed
    profile_data = profile().model_dump(mode="json")
    folder = f["private_path"].parent
    store = SnapshotStore(folder / "snapshots")
    files = {"src/app.py": b"old\n", "tests/test_app.py": b"def test_it(): assert True\n", "docs/guide.md": b"old\n"}
    revision = store.put(files)
    config = json.loads(f["policy_path"].read_text())
    config["resources"][0].update(workspace_revision=revision, execution_profiles={"isolated-python": profile_data})
    f["policy_path"].write_text(json.dumps(config))
    user_path, executor_path = folder / "users.json", folder / "executors.json"
    user_path.write_text(json.dumps([actor().model_copy(update={"token_sha256": hashlib.sha256(b"user-test").hexdigest()}).model_dump(mode="json")]))
    executor_path.write_text(json.dumps([executor(token_sha256=hashlib.sha256(b"broker-test").hexdigest()).model_dump(mode="json")]))
    cfg = ServerConfig(database_url=pg[1], identities_file=str(user_path), executor_identities_file=str(executor_path),
                       signing_key_file=str(f["private_path"]), signing_key_id="test-key",
                       verification_keys_file=str(f["public_path"]), action_policy_file=str(f["policy_path"]))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(create_app(cfg), log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline: time.sleep(0.05)
    assert server.started
    client = CoordinatorClient(url, "broker-test")
    broker = Broker(store, RestrictedRunner(development_desktop=True), client, f["keys"], "broker",
                    {"source": {"tenant_id": "tenant", "repository_id": "repo"}})
    def token(action):
        body = request(action, f["body"].session_id).model_copy(update={"workspace_revision": revision})
        decision = f["policy"].authorize(body, actor())
        return f["issuer"].issue(decision["id"], actor())
    try:
        yield dict(f=f, folder=folder, broker=broker, token=token, revision=revision, files=files, client=client, url=url)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


def test_real_http_claim_read_patch_and_terminal_immutability(connected):
    x = connected
    read = x["broker"].execute(x["token"]({"action_type": "READ_FILE", "path": "src/app.py"}))
    assert read["state"] == "completed" and read["outcome"]["content_base64"] == "b2xkCg=="
    patched = x["broker"].execute(x["token"](patch()))
    assert patched["state"] == "completed"
    assert x["broker"].store.get(patched["outcome"]["new_revision"])["src/app.py"] == b"new\n"
    assert x["broker"].store.get(x["revision"]) == x["files"]
    with pytest.raises(Exception):
        x["client"].call(f"/api/v1/executions/{read['execution_id']}/result", {"state": "cancelled", "outcome": {}})
    with x["f"]["policy"].store.engine.connect() as c:
        assert c.scalar(sa.select(executions.c.state).where(executions.c.id == read["execution_id"])) == "completed"


def test_separate_broker_process_runs_real_tests_and_replay_cannot_launch(connected):
    x = connected
    authorization = x["token"]({"action_type": "RUN_TESTS", "test_paths": ["tests/test_app.py"], "profile": "isolated-python"})
    token_path = x["folder"] / "token.json"
    token_path.write_text(json.dumps(authorization))
    config = dict(coordinator_url=x["url"], credential="broker-test", audience="broker",
        snapshot_store=str(x["broker"].store.root), verification_keys_file=str(x["f"]["public_path"]),
        resources={"source": {"tenant_id": "tenant", "repository_id": "repo"}})
    cfg_path = x["folder"] / "broker.json"
    cfg_path.write_text(json.dumps(config))
    env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE")}
    cmd = [sys.executable, "-m", "reposhield.broker", "--config", str(cfg_path), "--authorization", str(token_path), "--development-desktop"]
    result = subprocess.run(cmd, capture_output=True, env=env, timeout=45)
    assert result.returncode == 0, result.stderr.decode()
    body = json.loads(result.stdout)
    assert body["state"] == "completed" and body["outcome"]["mandatory_evidence_satisfied"]
    assert body["outcome"]["mode"] == "DEVELOPMENT EXECUTION"
    result2 = subprocess.run(cmd, capture_output=True, env=env, timeout=30)
    assert result2.returncode != 0
    with x["f"]["policy"].store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(executions)) == 1
    assert x["broker"].runner.command(["ps", "-a", "--filter", "label=reposhield.restricted=true", "--format", "{{.Names}}"]).strip() == b""


def test_invalid_signature_snapshot_or_revocation_cannot_start_job(connected):
    x = connected
    token = x["token"]({"action_type": "RUN_TESTS", "test_paths": ["tests/test_app.py"], "profile": "isolated-python"})
    bad = {**token, "signature": "A"*86}
    with pytest.raises(ValueError): x["broker"].execute(bad)
    store = x["broker"].store
    blob = store.root / (x["revision"][7:] + ".json")
    data = blob.read_bytes()
    blob.write_bytes(b"changed")
    with pytest.raises(ValueError): x["broker"].execute(token)
    blob.write_bytes(data)
    x["f"]["policy"].store.revoke_session(x["f"]["body"].session_id, "agent")
    with pytest.raises(Exception): x["broker"].execute(token)
    with x["f"]["policy"].store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(executions)) == 0


def test_execution_status_and_results_are_executor_scoped(signed):
    from tests.test_authorization import claim
    f = signed
    execution = claim(f)
    lifecycle = ExecutionService(f["policy"])
    assert lifecycle.status(execution["execution_id"], executor())["active"]
    with pytest.raises(HTTPException): lifecycle.status(execution["execution_id"], executor(id="other"))
    f["policy"].store.revoke_session(f["body"].session_id, "agent")
    assert not lifecycle.status(execution["execution_id"], executor())["active"]
    assert lifecycle.finish(execution["execution_id"], executor(), "completed", {})["state"] == "cancelled"


def test_real_coordinator_revocation_cancels_container(connected):
    x = connected
    files = {**x["files"], "tests/test_app.py": b'import time\ndef test_long(): time.sleep(60)\n'}
    revision = x["broker"].store.put(files)
    policy = json.loads(x["f"]["policy_path"].read_text())
    policy["resources"][0]["workspace_revision"] = revision
    x["f"]["policy_path"].write_text(json.dumps(policy))
    body = request({"action_type": "RUN_TESTS", "test_paths": ["tests/test_app.py"], "profile": "isolated-python"},
                   x["f"]["body"].session_id).model_copy(update={"workspace_revision": revision})
    decision = x["f"]["policy"].authorize(body, actor())
    token = x["f"]["issuer"].issue(decision["id"], actor())
    original_call = x["client"].call
    timers = []
    def call(path, data=None):
        value = original_call(path, data)
        if path == "/api/v1/actions/claim":
            timer = threading.Timer(2, lambda: x["f"]["policy"].store.revoke_session(body.session_id, "agent"))
            timers.append(timer)
            timer.start()
        return value
    x["client"].call = call
    try:
        result = x["broker"].execute(token)
        assert result["state"] == "cancelled"
    finally:
        for timer in timers: timer.join(timeout=5)
    assert x["broker"].runner.command(["ps", "-a", "--filter", "label=reposhield.restricted=true", "--format", "{{.Names}}"]).strip() == b""
