"""Real PostgreSQL integration: no SQLite substitution for locking/transaction evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("psycopg")
from alembic import command
from fastapi.testclient import TestClient

from reposhield.gitutil import resolve
from reposhield.server.admin import migration_config
from reposhield.server.app import create_app
from reposhield.server.config import ServerConfig
from reposhield.server.durable import DurableStore, LeaseLost, STAGES
from reposhield.server.process_worker import ProcessWorker
from reposhield.server.schema_v1 import (metadata, repositories, runs, attempts, tasks,
                                       events, outbox, sessions)


@pytest.fixture
def pg():
    url = os.environ.get("REPOSHIELD_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set REPOSHIELD_TEST_DATABASE_URL to run real PostgreSQL acceptance tests")
    schema = "rs_test_" + uuid.uuid4().hex
    root = sa.create_engine(url)
    with root.begin() as c:
        c.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    isolated = sa.engine.make_url(url).update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    store = DurableStore(isolated)
    try:
        command.upgrade(migration_config(isolated), "head")
        store.check_schema()
        yield store, isolated
    finally:
        store.engine.dispose()
        # Only the randomly named schema created above, never a caller's existing tables.
        with root.begin() as c:
            c.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()


@pytest.fixture
def registered(pg, demo_repo):
    store, _ = pg
    store.register_repository(repository_id="repo", tenant_id="tenant", name="demo",
                              path=demo_repo, base_sha=resolve(demo_repo, "main"))
    return store


def enqueue(store, demo_repo, branch="pr/docs-only", **kw):
    return store.enqueue("repo", resolve(demo_repo, branch), "actor", **kw)


def expire(store, claim):
    with store.engine.begin() as c:
        c.execute(tasks.update().where(tasks.c.id == claim["id"]).values(
            lease_until=sa.func.clock_timestamp() - sa.text("interval '1 second'")))


def make_ready(store):
    with store.engine.begin() as c:
        c.execute(tasks.update().where(tasks.c.state == "queued").values(available_at=sa.func.clock_timestamp()))


def parallel(fn, count=2):
    barrier = threading.Barrier(count)
    def call(i):
        barrier.wait()
        return fn(i)
    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(call, range(count)))


def test_migrations_roundtrip_and_postgres_constraints(pg):
    store, url = pg
    assert store.engine.dialect.name == "postgresql"
    assert set(metadata.tables) <= set(sa.inspect(store.engine).get_table_names())
    command.downgrade(migration_config(url), "base")
    assert "tasks" not in sa.inspect(store.engine).get_table_names()
    command.upgrade(migration_config(url), "head")
    store.check_schema()


def test_duplicate_intake_and_explicit_reruns_are_transactional(registered, demo_repo):
    store = registered
    same = parallel(lambda _: enqueue(store, demo_repo))
    assert same[0]["run_id"] == same[1]["run_id"]
    assert same[0]["attempt_id"] == same[1]["attempt_id"]
    rerun = enqueue(store, demo_repo, rerun_key="rerun-1")
    assert rerun["run_id"] == same[0]["run_id"] and rerun["attempt_id"] != same[0]["attempt_id"]
    assert enqueue(store, demo_repo, rerun_key="rerun-1")["attempt_id"] == rerun["attempt_id"]
    with store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(tasks)) == 2 * len(STAGES)
        assert c.scalar(sa.select(sa.func.count()).select_from(runs)) == 1


def test_intake_rolls_back_if_event_persistence_fails(registered, demo_repo, monkeypatch):
    def fail(*args, **kw):
        raise RuntimeError("injected storage failure")
    monkeypatch.setattr(registered, "_event", fail)
    with pytest.raises(RuntimeError):
        enqueue(registered, demo_repo)
    with registered.engine.connect() as c:
        for table in (runs, attempts, tasks):
            assert c.scalar(sa.select(sa.func.count()).select_from(table)) == 0


def test_two_workers_cannot_claim_or_finalize_the_same_lease(registered, demo_repo):
    store = registered
    enqueue(store, demo_repo)
    claims = parallel(lambda i: store.claim(f"worker-{i}"))
    claim, = [c for c in claims if c is not None]
    assert claim["stage"] == "snapshot"
    assert store.claim("third") is None  # dependent analyze cannot run ahead
    def finish(_):
        try:
            store.complete(claim, {"real": "observation"})
            return "won"
        except LeaseLost:
            return "lost"
    assert sorted(parallel(finish)) == ["lost", "won"]
    with store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(events).where(events.c.kind == "TASK_COMPLETED")) == 1
    assert store.claim("next")["stage"] == "analyze"


def test_restart_reclaims_expired_work_and_fences_old_worker(registered, pg, demo_repo):
    enqueue(registered, demo_repo)
    old = registered.claim("old")
    expire(registered, old)
    restarted = DurableStore(pg[1])
    try:
        assert restarted.recover_expired() == 1
        make_ready(restarted)
        new = restarted.claim("new")
        assert new["id"] == old["id"] and new["lease_epoch"] > old["lease_epoch"]
        for operation in (lambda: registered.complete(old, {}), lambda: registered.heartbeat(old),
                          lambda: registered.fail(old, "late")):
            with pytest.raises(LeaseLost):
                operation()
        restarted.complete(new, {})
    finally:
        restarted.engine.dispose()


def test_heartbeat_keeps_live_worker_and_does_not_resurrect_expired_lease(registered, demo_repo):
    enqueue(registered, demo_repo)
    claim = registered.claim("worker", lease_seconds=1)
    registered.heartbeat(claim, lease_seconds=30)
    assert registered.recover_expired() == 0
    expire(registered, claim)
    with pytest.raises(LeaseLost):
        registered.heartbeat(claim)


def test_expired_lease_cannot_finalize_even_before_recovery(registered, demo_repo):
    enqueue(registered, demo_repo)
    claim = registered.claim("worker")
    expire(registered, claim)
    with pytest.raises(LeaseLost):
        registered.complete(claim, {"verdict": "PASS"})


@pytest.mark.parametrize("crash", [False, True])
def test_retry_budget_is_bounded_and_cancels_dependents(registered, demo_repo, crash):
    job = enqueue(registered, demo_repo)
    for i in range(3):
        claim = registered.claim(f"worker-{i}")
        assert claim["tries"] == i + 1
        if crash:
            expire(registered, claim)
            registered.recover_expired()
        else:
            registered.fail(claim, "infrastructure_failure")
        make_ready(registered)
    assert registered.claim("fourth") is None
    attempt = registered.get_attempt(job["attempt_id"])
    assert attempt["state"] == "failed-infrastructure" and attempt["result"] is None
    assert sorted(t["state"] for t in attempt["tasks"]) == ["cancelled"] * 4 + ["failed"]


@pytest.mark.parametrize("branch,verdict", [("pr/docs-only", "PASS"), ("pr/safe-refactor", "REVIEW_REQUIRED"),
                                           ("pr/analytics-leak", "BLOCK")])
def test_real_static_worker_dag_preserves_evidence_and_outbox(registered, demo_repo, branch, verdict):
    job = enqueue(registered, demo_repo, branch)
    worker = ProcessWorker(registered)
    for _ in STAGES:
        assert worker.run_once()
    assert not worker.run_once()
    attempt = registered.get_attempt(job["attempt_id"])
    assert attempt["state"] == "completed" and attempt["result"]["verdict"] == verdict
    assert attempt["result"]["mode"] == "VERIFICATION ONLY"
    assert attempt["result"]["tests"]["status"] != "RAN"
    assert all(t["state"] == "succeeded" for t in attempt["tasks"])
    with registered.engine.connect() as c:
        rows = c.execute(sa.select(outbox)).mappings().all()
        assert len(rows) == 1 and rows[0]["state"] == "pending"
        assert rows[0]["payload"]["verdict"] == verdict


def test_publication_transaction_rolls_back_as_a_unit(registered, demo_repo, monkeypatch):
    job = enqueue(registered, demo_repo)
    worker = ProcessWorker(registered)
    for _ in STAGES[:-1]:
        assert worker.run_once()
    claim = registered.claim("publisher")
    original = registered._event
    def event(c, kind, *args, **kw):
        if kind == "ATTEMPT_COMPLETED":
            raise RuntimeError("publication transaction interrupted")
        return original(c, kind, *args, **kw)
    monkeypatch.setattr(registered, "_event", event)
    with pytest.raises(RuntimeError):
        registered.complete(claim, {"delivery": "pending"})
    assert registered.get_attempt(job["attempt_id"])["state"] == "running"
    with registered.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(outbox)) == 0
    monkeypatch.setattr(registered, "_event", original)
    registered.complete(claim, {})
    assert registered.get_attempt(job["attempt_id"])["state"] == "completed"


def test_separate_worker_process_runs_actual_stage(registered, pg, demo_repo):
    job = enqueue(registered, demo_repo)
    env = {**os.environ, "REPOSHIELD_DATABASE_URL": pg[1]}
    result = subprocess.run([sys.executable, "-m", "reposhield.server.process_worker", "--once"],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    attempt = registered.get_attempt(job["attempt_id"])
    assert next(t for t in attempt["tasks"] if t["stage"] == "snapshot")["state"] == "succeeded"
    assert next(t for t in attempt["tasks"] if t["stage"] == "analyze")["state"] == "queued"


def test_worker_process_crash_is_recovered_by_restarted_process(registered, pg, demo_repo):
    job = enqueue(registered, demo_repo)
    env = {**os.environ, "REPOSHIELD_DATABASE_URL": pg[1]}
    crash = "import os; from reposhield.server.durable import DurableStore; s=DurableStore(os.environ['REPOSHIELD_DATABASE_URL']); assert s.claim('crashed-worker', 1); os._exit(23)"
    dead = subprocess.run([sys.executable, "-c", crash], env=env, capture_output=True, timeout=30)
    assert dead.returncode == 23
    with registered.engine.connect() as c:
        old = dict(c.execute(sa.select(tasks).where(tasks.c.attempt_id == job["attempt_id"],
                                                   tasks.c.state == "running")).mappings().one())
    expire(registered, old)
    cmd = [sys.executable, "-m", "reposhield.server.process_worker", "--once"]
    assert subprocess.run(cmd, env=env, capture_output=True, timeout=30).returncode == 0
    make_ready(registered)  # advance the bounded retry delay without waiting on wall time
    assert subprocess.run(cmd, env=env, capture_output=True, timeout=30).returncode == 0
    with registered.engine.connect() as c:
        current = c.execute(sa.select(tasks).where(tasks.c.id == old["id"])).mappings().one()
        assert current["state"] == "succeeded" and current["lease_epoch"] == 2 and current["tries"] == 2


def test_worker_renews_lease_during_slow_stage(registered, demo_repo, monkeypatch):
    job = enqueue(registered, demo_repo)
    worker = ProcessWorker(registered, lease_seconds=1)
    real_handle = worker.handle
    def slow(claim):
        time.sleep(1.5)
        assert registered.recover_expired() == 0
        return real_handle(claim)
    monkeypatch.setattr(worker, "handle", slow)
    assert worker.run_once()
    assert next(t for t in registered.get_attempt(job["attempt_id"])["tasks"]
                if t["stage"] == "snapshot")["state"] == "succeeded"


def test_two_independent_worker_processes_cannot_finalize_same_lease(registered, pg, demo_repo):
    enqueue(registered, demo_repo)
    claim = registered.claim("worker")
    binding = json.dumps({key: claim[key] for key in ("id", "lease_owner", "lease_epoch")})
    script = """import os, sys, json
from reposhield.server.durable import DurableStore, LeaseLost
s = DurableStore(os.environ['REPOSHIELD_DATABASE_URL'])
try:
    s.complete(json.loads(sys.argv[1]), {'observed': True})
except LeaseLost:
    sys.exit(17)
"""
    env = {**os.environ, "REPOSHIELD_DATABASE_URL": pg[1]}
    procs = [subprocess.Popen([sys.executable, "-c", script, binding], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    try:
        for proc in procs:
            proc.communicate(timeout=30)
        assert sorted(proc.returncode for proc in procs) == [0, 17]
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def test_registered_base_and_implementation_profile_bind_logical_identity(registered, demo_repo):
    first = enqueue(registered, demo_repo)
    with registered.engine.begin() as c:
        c.execute(repositories.update().where(repositories.c.id == "repo").values(policy_epoch=2))
    second = enqueue(registered, demo_repo)
    assert second["run_id"] != first["run_id"]


def test_snapshot_failure_cannot_execute_tests_or_produce_green_result(registered):
    job = registered.enqueue("repo", "f" * 40, "actor")
    worker = ProcessWorker(registered)
    for _ in range(3):
        assert worker.run_once()
        make_ready(registered)
    attempt = registered.get_attempt(job["attempt_id"])
    assert attempt["state"] == "failed-infrastructure" and attempt["result"] is None
    assert all(t["state"] == "cancelled" for t in attempt["tasks"] if t["stage"] != "snapshot")


@pytest.fixture
def client(registered, pg, tmp_path, demo_repo):
    registered.register_repository(repository_id="other", tenant_id="tenant", name="other",
        path=demo_repo, base_sha=resolve(demo_repo, "main"))
    registered.register_repository(repository_id="foreign", tenant_id="foreign-tenant", name="foreign",
        path=demo_repo, base_sha=resolve(demo_repo, "main"))
    identities = [{"id": role, "tenant_id": "tenant", "role": role, "repository_ids": ["repo"],
                   "token_sha256": hashlib.sha256(f"test-{role}".encode()).hexdigest()}
                  for role in ("administrator", "reviewer", "viewer", "agent")]
    identities.append({"id": "agent2", "tenant_id": "tenant", "role": "agent", "repository_ids": ["repo"],
                       "token_sha256": hashlib.sha256(b"test-agent2").hexdigest()})
    path = tmp_path / "identities.json"
    path.write_text(json.dumps(identities))
    app = create_app(ServerConfig(database_url=pg[1], identities_file=str(path)), start_workers=True)
    assert not hasattr(app.state, "worker")  # even default lifespan cannot start API-host execution
    with TestClient(app) as test_client:
        yield test_client


def headers(role="agent"):
    return {"Authorization": f"Bearer test-{role}"}


def test_api_authentication_role_and_repository_guards(client, demo_repo):
    head = resolve(demo_repo, "pr/docs-only")
    route = "/api/v1/repositories/repo/runs"
    assert client.post(route, json={"head_sha": head}).status_code == 401
    assert client.post(route, json={"head_sha": head}, headers=headers("viewer")).status_code == 403
    for repo in ("other", "foreign", "missing"):
        assert client.post(f"/api/v1/repositories/{repo}/runs", json={"head_sha": head}, headers=headers()).status_code == 404
    for extra in ({"base_sha": head}, {"run_tests": True}, {"policy_path": "agent-policy"}, {"rerun": True}):
        assert client.post(route, json={"head_sha": head, **extra}, headers=headers()).status_code == 422
    job = client.post(route, json={"head_sha": head}, headers=headers()).json()
    assert client.get(f"/api/v1/runs/{job['run_id']}", headers=headers("viewer")).status_code == 200
    assert client.get(f"/api/v1/attempts/{job['attempt_id']}/events", headers=headers("viewer")).status_code == 200


def test_cross_repository_run_ids_do_not_leak(client, registered, demo_repo):
    job = registered.enqueue("other", resolve(demo_repo, "main"), "administrator")
    for path in (f"/api/v1/runs/{job['run_id']}", f"/api/v1/attempts/{job['attempt_id']}",
                 f"/api/v1/attempts/{job['attempt_id']}/events"):
        assert client.get(path, headers=headers()).status_code == 404


def test_session_ownership_expiration_and_revocation(client, registered):
    sid = client.post("/api/v1/sessions", json={"repository_id": "repo"}, headers=headers()).json()["id"]
    body = {"schema_version": 2, "tenant_id": "tenant", "repository_id": "repo", "session_id": sid,
            "workspace_revision": "sha256:" + "a" * 64, "action": {"action_type": "READ_FILE", "path": "a.py"}}
    route = "/api/v1/actions/authorize"
    assert client.post(route, json=body).status_code == 401
    assert client.post(route, json=body, headers=headers("agent2")).status_code == 403
    assert client.post(route, json=body, headers=headers()).status_code == 501
    assert client.post(route, json={**body, "repository_id": "other"}, headers=headers()).status_code == 403
    with registered.engine.begin() as c:
        c.execute(sessions.update().where(sessions.c.id == sid).values(expires_at=sa.func.clock_timestamp()))
    assert client.post(route, json=body, headers=headers()).status_code == 403
    assert client.post(f"/api/v1/sessions/{sid}/revoke", headers=headers("agent2")).status_code == 403
    assert client.post(f"/api/v1/sessions/{sid}/revoke", headers=headers()).status_code == 200
    assert registered.get_session(sid)["state"] == "revoked"


def test_action_execution_and_approval_never_anonymous_or_agent_approved(client):
    for path in ("/api/v1/actions/execute", "/api/v1/actions/x/approve"):
        assert client.post(path).status_code == 401
    assert client.post("/api/v1/actions/x/approve", headers=headers()).status_code == 403
    assert client.post("/api/v1/actions/x/approve", headers=headers("reviewer")).status_code == 501
    assert client.post("/api/v1/actions/execute", headers=headers()).status_code == 501


def test_coordinator_requires_identity_configuration(pg):
    with pytest.raises(RuntimeError, match="anonymous"):
        create_app(ServerConfig(database_url=pg[1], identities_file=None))


def test_durable_store_rejects_sqlite():
    with pytest.raises(ValueError, match="PostgreSQL"):
        DurableStore("sqlite:///:memory:")
