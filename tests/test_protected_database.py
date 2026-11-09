"""Real-service development demo; opt-in Docker, no mocks and no customer data."""
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from reposhield.protected_demo import inspect_database, require_unchanged, MAX_ROWS
from reposhield.server.schema_v1 import executions
from tests.test_broker import connected, signed, service, pg, registered, actor, request


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, timeout=30)
    # Do not include command arguments or DB container inspection in failure output.
    if result.returncode:
        raise RuntimeError("protected demo Docker operation failed")
    return result.stdout


class ProtectedDatabase(dict):
    def __repr__(self):
        return "<disposable synthetic database; credentials redacted>"


@pytest.fixture
def protected_database():
    if os.environ.get("REPOSHIELD_TEST_PROTECTED_DATABASE") != "1":
        pytest.skip("requires explicit disposable protected database opt-in")
    name = "reposhield-protected-" + uuid.uuid4().hex
    owner_password, verifier_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    # Docker CLI inherits these only for trusted database provisioning, never runner execution.
    environment = {**os.environ, "POSTGRES_PASSWORD": owner_password}
    started = False
    try:
        result = subprocess.run(["docker", "run", "--detach", "--rm", "--pull=never", "--name", name,
            "--memory", "256m", "--cpus", "0.5", "-p", "127.0.0.1::5432",
            "-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_USER=shop_owner", "-e", "POSTGRES_DB=synthetic_shop",
            "postgres:17"], env=environment, capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError("could not start disposable protected database")
        started = True
        inspection = json.loads(docker("inspect", name))[0]
        port = int(inspection["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"])
        ip = inspection["NetworkSettings"]["Networks"]["bridge"]["IPAddress"]
        assert ip and inspection["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostIp"] == "127.0.0.1"
        owner = make_conninfo(host="127.0.0.1", port=port, dbname="synthetic_shop", user="shop_owner", password=owner_password)
        deadline = time.monotonic() + 25
        while True:
            try:
                connection = psycopg.connect(owner, connect_timeout=2)
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("protected database readiness timed out") from None
                time.sleep(0.2)
        with connection:
            connection.execute(Path("tests/fixtures/protected_shop.sql").read_text())
            connection.execute(sql.SQL("CREATE ROLE shop_verifier LOGIN PASSWORD {}").format(sql.Literal(verifier_password)))
            connection.execute("GRANT CONNECT ON DATABASE synthetic_shop TO shop_verifier")
            connection.execute("GRANT USAGE ON SCHEMA public TO shop_verifier")
            connection.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO shop_verifier")
        verifier = make_conninfo(host="127.0.0.1", port=port, dbname="synthetic_shop", user="shop_verifier", password=verifier_password)
        yield ProtectedDatabase(owner=owner, verifier=verifier, ip=ip, port=port,
                                secrets=(owner_password, verifier_password))
    finally:
        if started:
            docker("stop", "--time", "2", name)


def test_real_protected_shop_workflow_and_bypass(connected, protected_database):
    x, db = connected, protected_database
    before = inspect_database(db["verifier"])
    assert all(t["rows"] == 2 for t in before["tables"].values())
    # A live host connection with a deliberately incorrect credential must specifically
    # fail authentication. A timeout, offline database, or missing driver cannot pass.
    with pytest.raises(psycopg.OperationalError, match="password authentication failed"):
        psycopg.connect(make_conninfo(db["verifier"], password="deliberately-wrong"), connect_timeout=3)
    with psycopg.connect(db["verifier"]) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("DELETE FROM public.orders")
    # Same DB IP/port is reachable from the ordinary bridge, without any credentials.
    # This control prevents a wrong address or unavailable service masquerading as isolation.
    image_id = os.environ["REPOSHIELD_TEST_RUNNER_IMAGE"].split("@", 1)[1]
    docker("run", "--rm", "--pull=never", "--network=bridge", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--memory=64m", "--cpus=0.5", "--pids-limit=16",
        "--entrypoint=python", image_id, "-I", "-c",
        "import socket; socket.create_connection((" + repr(db["ip"]) + ", 5432), timeout=3).close()")

    # Only endpoint coordinates go into the candidate snapshot. Credentials stay outside.
    probe = '''import os, socket
import pytest
from src.app import total

def test_allowed_edit():
    assert total(500, 2) == 1000

@pytest.mark.parametrize("host,port", ENDPOINTS)
def test_direct_database_network_bypass(host, port):
    with pytest.raises(OSError):
        with socket.create_connection((host, port), timeout=0.5):
            pytest.fail("protected service unexpectedly reachable")

def test_no_privileged_environment_or_mounts():
    assert not any(k.startswith(("POSTGRES", "PG", "REPOSHIELD", "AWS", "AZURE", "GITHUB")) for k in os.environ)
    for path in ("/var/run/docker.sock", "/root/.aws", "/root/.ssh", "/run/secrets", "/host", "/host_mnt"):
        assert not os.path.lexists(path)
'''.replace("ENDPOINTS", repr([(db["ip"], 5432), ("127.0.0.1", db["port"])]))
    files = {"src/app.py": b"def total(price, quantity):\n    return price + quantity\n",
             "tests/test_app.py": probe.encode()}
    revision = x["broker"].store.put(files)

    def activate(revision):
        # Trusted test provisioner advances the policy; no agent policy-writing action exists.
        policy = json.loads(x["f"]["policy_path"].read_text())
        policy["resources"][0]["workspace_revision"] = revision
        x["f"]["policy_path"].write_text(json.dumps(policy))

    def authorize(action, revision):
        body = request(action, x["f"]["body"].session_id).model_copy(update={"workspace_revision": revision})
        return x["f"]["policy"].authorize(body, actor())

    activate(revision)
    denied = authorize({"action_type": "DATABASE_OPERATION", "resource_id": "protected-shop"}, revision)
    assert denied["decision"] == "DENY"
    with pytest.raises(HTTPException) as error:
        x["f"]["issuer"].issue(denied["id"], actor())
    assert error.value.status_code == 409
    assert error.value.detail == "decision expired, denied or context changed"
    with x["f"]["policy"].store.engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(executions)) == 0
    patch = {"action_type": "APPLY_PATCH", "patch": "--- a/src/app.py\n+++ b/src/app.py\n@@ -1,2 +1,2 @@\n def total(price, quantity):\n-    return price + quantity\n+    return price * quantity\n"}
    decision = authorize(patch, revision)
    assert decision["decision"] == "ALLOW"
    edited = x["broker"].execute(x["f"]["issuer"].issue(decision["id"], actor()))
    assert edited["state"] == "completed"
    new_revision = edited["outcome"]["new_revision"]
    assert x["broker"].store.get(revision) == files
    activate(new_revision)
    decision = authorize({"action_type": "RUN_TESTS", "test_paths": ["tests/test_app.py"], "profile": "isolated-python"}, new_revision)
    result = x["broker"].execute(x["f"]["issuer"].issue(decision["id"], actor()))
    assert result["state"] == "completed"
    outcome = result["outcome"]
    assert outcome["mandatory_evidence_satisfied"] and outcome["observed_cases"] == 4
    assert outcome["isolation"]["NetworkMode"] == "none"
    assert not outcome["isolation"].get("Binds")
    after = inspect_database(db["verifier"])
    require_unchanged(before, after)
    report = {"mode": "DEVELOPMENT EXECUTION", "vm_acceptance": "pending", "before": before, "after": after,
        "policy_denial": {"decision": denied["decision"], "reason": denied["reason"], "token_issued": False},
        "credential_control": "live database rejected incorrect password",
        "network_control": "same protected DB IP:5432 reachable from trusted bridge control; denied in network-none sandbox",
        "verifier_permissions": "SELECT allowed; DELETE rejected",
        "allowed_patch": edited, "sandbox_tests": result, "database_unchanged": True}
    serialized = json.dumps(report, indent=2)
    for secret in (*db["secrets"], x["f"]["private_path"].read_text()):
        assert secret not in serialized and all(secret.encode() not in data for data in files.values())
    if os.environ.get("REPOSHIELD_TEST_EVIDENCE_DIR"):
        output = Path(os.environ["REPOSHIELD_TEST_EVIDENCE_DIR"])
        output.mkdir(parents=True, exist_ok=True)
        (output / "protected-database.json").write_text(serialized)


def test_trusted_verifier_detects_content_count_missing_and_oversized_tables(protected_database):
    db = protected_database
    original = inspect_database(db["verifier"])
    with psycopg.connect(db["owner"]) as connection:
        connection.execute("UPDATE public.products SET price_cents = price_cents + 1 WHERE id = 1")
    changed = inspect_database(db["verifier"])
    assert changed["tables"]["products"]["rows"] == original["tables"]["products"]["rows"]
    with pytest.raises(ValueError, match="changed"):
        require_unchanged(original, changed)
    with psycopg.connect(db["owner"]) as connection:
        connection.execute("DELETE FROM public.orders WHERE id = 1")
    assert inspect_database(db["verifier"])["tables"]["orders"]["rows"] == 1
    with pytest.raises(ValueError, match="changed"):
        require_unchanged(original, inspect_database(db["verifier"]))
    with psycopg.connect(db["owner"]) as connection:
        connection.execute("INSERT INTO public.products SELECT i, 'Synthetic excess', 1 FROM generate_series(3, %s) i", (MAX_ROWS + 1,))
    with pytest.raises(ValueError, match="row bound"):
        inspect_database(db["verifier"])
    with psycopg.connect(db["owner"]) as connection:
        connection.execute("DELETE FROM public.products WHERE id > 2")
        connection.execute("DROP TABLE public.orders")
    with pytest.raises(psycopg.errors.UndefinedTable):
        inspect_database(db["verifier"])


@pytest.mark.parametrize("evidence", [None, {}, {"version": 1, "tables": {}},
    {"version": 1, "tables": {"products": {"exists": False}}}])
def test_missing_database_evidence_never_satisfies_unchanged(evidence):
    with pytest.raises(ValueError):
        require_unchanged(evidence, copy.deepcopy(evidence))


@pytest.mark.parametrize("fault", ["empty", "absent", "boolean_count", "invalid_hash", "digest"])
def test_matching_but_invalid_database_evidence_is_rejected(fault):
    tables = {name: {"exists": True, "rows": 2, "sha256": "a" * 64}
              for name in ("products", "customers", "orders")}
    if fault == "empty": tables["orders"]["rows"] = 0
    if fault == "absent": tables["orders"]["exists"] = False
    if fault == "boolean_count": tables["orders"]["rows"] = True
    if fault == "invalid_hash": tables["orders"]["sha256"] = "z" * 64
    digest = hashlib.sha256(json.dumps(tables, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    evidence = {"version": 1, "tables": tables, "sha256": digest if fault != "digest" else "b" * 64}
    with pytest.raises(ValueError):
        require_unchanged(evidence, copy.deepcopy(evidence))
