"""Real PostgreSQL/crypto/worker checks with simulated GitHub HTTP responses.

These are local regression tests, not live GitHub acceptance evidence.
"""
import base64
import copy
import json
import os
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from fastapi import HTTPException
from fastapi.testclient import TestClient

from reposhield.gitutil import resolve
from reposhield.server.github import sign
from reposhield.server.github_app import AppClient, AppConfig, GitHubError, AccessRevoked, load_config
from reposhield.server.github_service import GitHubService, CHECK_NAME
from reposhield.server.schema_v5 import deliveries, checks, installations
from reposhield.server.schema_v1 import attempts, tasks, runs, outbox
from reposhield.server.config import ServerConfig
from reposhield.server.process_worker import ProcessWorker
from tests.test_authorization import signed, service, pg, registered

SECRET = "disposable-webhook-secret-" + "x" * 32


class GitHubTransport:
    """Simulated HTTP boundary; never reported as a real GitHub connection."""
    def __init__(self, base, head):
        self.pr = {"number": 1, "state": "open", "base": {"sha": base, "ref": "main", "repo": {"id": 3}}, "head": {"sha": head}}
        self.remote_checks, self.calls = [], []
        self.revoked, self.fail_patch, self.lose_create_response = False, False, False

    def __call__(self, method, url, headers, body):
        assert url.startswith("https://api.github.com/")
        path = url[len("https://api.github.com"):]
        payload = json.loads(body) if body else None
        self.calls.append((method, path, payload))  # Deliberately no authentication headers retained.
        if self.revoked: return 401, {}
        if path == "/app/installations/2": return 200, {"id": 2, "app_id": 1, "suspended_at": None}
        if path == "/app/installations/2/access_tokens":
            assert payload == {"repository_ids": [3], "permissions": {"contents": "read", "pull_requests": "read", "checks": "write"}}
            return 201, {"token": "ephemeral-installation-test-token"}
        assert headers["Authorization"] == "Bearer ephemeral-installation-test-token"
        if path == "/repos/demo/shop": return 200, {"id": 3, "full_name": "demo/shop", "private": False}
        if path == "/repos/demo/shop/pulls/1": return 200, copy.deepcopy(self.pr)
        if "/commits/" in path:
            sha = path.split("/commits/")[1].split("/")[0]
            return 200, {"check_runs": [copy.deepcopy(r) for r in self.remote_checks if r["head_sha"] == sha]}
        if path == "/repos/demo/shop/check-runs" and method == "POST":
            check = {**payload, "id": len(self.remote_checks) + 1, "app": {"id": 1}}
            self.remote_checks.append(check)
            if self.lose_create_response:
                self.lose_create_response = False
                raise GitHubError("simulated_lost_response")
            return 201, copy.deepcopy(check)
        if "/check-runs/" in path:
            check = next(r for r in self.remote_checks if r["id"] == int(path.rsplit("/", 1)[1]))
            if method == "PATCH":
                if self.fail_patch: return 500, {}
                check.update(payload)
            return 200, copy.deepcopy(check)
        raise AssertionError("unexpected simulated endpoint")


@pytest.fixture
def github(signed, demo_repo):
    f = signed
    folder = f["private_path"].parent
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_path = folder / "github-rsa.pem"
    rsa_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    secret = folder / "webhook-secret.txt"
    secret.write_text(SECRET)
    app = AppConfig(app_id=1, installation_id=2, remote_repository_id=3, repository_id="repo", full_name="demo/shop",
                    private_key_file=str(rsa_path), webhook_secret_file=str(secret))
    config_path = folder / "github-app.json"
    config_path.write_text(app.model_dump_json())
    cfg = ServerConfig(github_app_config_file=str(config_path), signing_key_file=str(f["private_path"]),
                       signing_key_id="test-key", verification_keys_file=str(f["public_path"]))
    transport = GitHubTransport(resolve(demo_repo, "main"), resolve(demo_repo, "pr/docs-only"))
    client = AppClient(app, [str(Path.cwd()), demo_repo], transport)
    fetches = []
    def fetch(repo, config, pr):
        fetches.append(pr["head"]["sha"])
        assert resolve(demo_repo, pr["head"]["sha"]) == pr["head"]["sha"]
        return pr["base"]["sha"]  # Simulated fetch; actual local Git objects power the worker.
    svc = GitHubService(f["policy"].store, cfg, client, fetch)
    svc.onboard()
    return dict(svc=svc, cfg=cfg, transport=transport, client=client, key=key, f=f, fetches=fetches, demo=demo_repo)


def receive(x, delivery="delivery-1", **updates):
    payload = {"installation": {"id": 2}, "repository": {"id": 3}, "action": "synchronize", "pull_request": {"number": 1}, **updates}
    raw = json.dumps(payload).encode()
    return x["svc"].receive(delivery, "pull_request", sign(SECRET, raw), raw)


def ready(x, table=checks):
    with x["svc"].store.engine.begin() as c:
        c.execute(table.update().values(available_at=sa.func.now() - sa.text("interval '1 second'")))


def test_app_jwt_real_rsa_and_scoped_installation_auth(github):
    x = github
    jwt = x["client"].jwt()
    header, payload, signature = jwt.split(".")
    decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    assert json.loads(decode(header))["alg"] == "RS256"
    claims = json.loads(decode(payload))
    assert claims["iss"] == "1" and claims["iat"] <= time.time() < claims["exp"] <= time.time() + 600
    x["key"].public_key().verify(decode(signature), (header + "." + payload).encode(), padding.PKCS1v15(), hashes.SHA256())
    assert x["client"].installation_token() == "ephemeral-installation-test-token"
    with pytest.raises(ValueError): load_config(x["cfg"].github_app_config_file, [str(Path(x["cfg"].github_app_config_file).parent)])


@pytest.mark.parametrize("signature", [None, "sha256=" + "0"*64, "sha1=bad", "sha256=\u00e9"])
def test_invalid_webhook_never_persists_intent(github, signature):
    with pytest.raises(HTTPException) as error: github["svc"].receive("delivery", "pull_request", signature, b"{}")
    assert error.value.status_code == 401
    with github["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(deliveries)) == 0


def test_duplicate_delivery_and_atomic_run_intake(github):
    x = github
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: receive(x), range(2)))
    assert sorted(r["duplicate"] for r in results) == [False, True]
    with pytest.raises(HTTPException) as error: receive(x, action="opened")
    assert error.value.status_code == 409
    assert x["svc"].run_once()
    assert not x["svc"].run_once()
    receive(x, "delivery-2")
    assert x["svc"].run_once()
    with x["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(attempts)) == 1
        assert c.scalar(sa.select(sa.func.count()).select_from(checks)) == 1
        assert set(c.scalars(sa.select(deliveries.c.state))) == {"processed"}
        inputs = c.scalar(sa.select(runs.c.inputs))
        assert inputs["github"]["execution_tree"] == x["transport"].pr["head"]["sha"]


def test_intake_rolls_back_run_and_outbox_on_failure(github, monkeypatch):
    x = github
    receive(x)
    original = x["svc"].store.enqueue
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("test failure after enqueue")
    monkeypatch.setattr(x["svc"].store, "enqueue", fail)
    x["svc"].run_once()
    with x["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(attempts)) == 0
        assert c.scalar(sa.select(sa.func.count()).select_from(checks)) == 0
        assert c.scalar(sa.select(deliveries.c.state)) == "pending"
    monkeypatch.setattr(x["svc"].store, "enqueue", original)
    ready(x, deliveries)
    assert x["svc"].run_once()


def test_reordered_events_use_current_pr_and_old_checks_cannot_publish(github):
    x = github
    receive(x, "A")
    x["svc"].run_once()
    old = x["transport"].pr["head"]["sha"]
    x["transport"].pr["head"]["sha"] = resolve(x["demo"], "pr/safe-refactor")
    receive(x, "B")
    x["svc"].run_once()
    receive(x, "late-A", pull_request={"number": 1, "head": {"sha": old}})
    x["svc"].run_once()
    assert x["fetches"][-1] != old
    x["svc"].run_once(publishing=True)
    with x["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(checks.c.state).where(checks.c.head_sha == old)) == "obsolete"
        assert c.scalar(sa.select(sa.func.count()).select_from(attempts)) == 2
    assert not x["transport"].remote_checks


@pytest.mark.parametrize("branch,expected,title", [("pr/docs-only", "success", "PASS"),
    ("pr/safe-refactor", "failure", "REVIEW_REQUIRED"), ("pr/analytics-leak", "failure", "BLOCK")])
def test_real_static_worker_and_signed_evidence_publish_correct_conclusion(github, branch, expected, title):
    x = github
    x["transport"].pr["head"]["sha"] = resolve(x["demo"], branch)
    receive(x)
    x["svc"].run_once()
    x["svc"].run_once(publishing=True)
    assert x["transport"].remote_checks[0]["status"] == "queued"
    worker = ProcessWorker(x["svc"].store)
    for _ in range(5): assert worker.run_once()
    ready(x)
    x["svc"].run_once(publishing=True)
    check = x["transport"].remote_checks[0]
    assert check["conclusion"] == expected and check["output"]["title"].startswith(title)
    with x["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(checks.c.state)) == "published"
        assert c.scalar(sa.select(outbox.c.state)) == "published"
        assert c.scalar(sa.select(checks.c.checkpoint_id))


def test_lost_create_response_reconciles_and_publication_retries_are_bounded(github):
    x = github
    receive(x)
    x["svc"].run_once()
    x["transport"].lose_create_response = True
    x["svc"].run_once(publishing=True)
    assert len(x["transport"].remote_checks) == 1
    ready(x)
    x["svc"].run_once(publishing=True)
    assert len(x["transport"].remote_checks) == 1
    worker = ProcessWorker(x["svc"].store)
    for _ in range(5): worker.run_once()
    x["transport"].fail_patch = True
    for _ in range(6):
        ready(x)
        x["svc"].run_once(publishing=True)
    with x["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(checks.c.state)) == "failed"
        assert c.scalar(sa.select(checks.c.tries)) == 5
    assert "conclusion" not in x["transport"].remote_checks[0]


@pytest.mark.parametrize("event,action,extra", [("installation", "deleted", {}), ("installation", "suspend", {}),
    ("installation_repositories", "removed", {"repositories_removed": [{"id": 3}]})])
def test_revocation_stops_new_scheduling_and_publication(github, event, action, extra):
    x = github
    receive(x)
    x["svc"].run_once()
    raw = json.dumps({"installation": {"id": 2}, "action": action, **extra}).encode()
    x["svc"].receive("revoke", event, sign(SECRET, raw), raw)
    assert x["svc"].store.claim("should-not-run") is None
    with pytest.raises(HTTPException): receive(x, "after-revoke")
    x["svc"].run_once(publishing=True)
    assert not x["transport"].remote_checks


def test_remote_auth_revocation_and_changed_base_fail_closed(github):
    x = github
    receive(x)
    x["transport"].pr["base"]["sha"] = "f" * 40
    x["svc"].run_once()
    with x["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(attempts)) == 0
    ready(x, deliveries)
    x["transport"].revoked = True
    x["svc"].run_once()
    with x["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(installations.c.enabled)) is False


def test_infrastructure_failure_is_non_success(github):
    x = github
    receive(x)
    x["svc"].run_once()
    for _ in range(3):
        ready(x, tasks)
        claim = x["svc"].store.claim("failure-fixture")
        x["svc"].store.fail(claim, "FixtureInfrastructureFailure")
    x["svc"].run_once(publishing=True)
    check = x["transport"].remote_checks[0]
    assert check["conclusion"] == "failure" and check["output"]["title"] == "Infrastructure failure"


def test_webhook_route_is_signed_bounded_and_never_executes(github, pg):
    from reposhield.server.app import create_app
    import hashlib
    x = github
    users = Path(x["cfg"].github_app_config_file).parent / "users.json"
    users.write_text(json.dumps([{"id": "user", "tenant_id": "tenant", "role": "viewer", "repository_ids": ["repo"],
                                 "token_sha256": hashlib.sha256(b"user").hexdigest()}]))
    x["cfg"].database_url, x["cfg"].identities_file = pg[1], str(users)
    raw = json.dumps({"installation": {"id": 2}, "repository": {"id": 3}, "action": "opened", "pull_request": {"number": 1}}).encode()
    headers = {"X-GitHub-Delivery": "route-delivery", "X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sign(SECRET, raw)}
    with TestClient(create_app(x["cfg"])) as client:
        assert client.post("/api/v1/github/webhook", content=raw).status_code == 422
        assert client.post("/api/v1/github/webhook", content=raw, headers=headers).status_code == 202
        assert client.post("/api/v1/github/webhook", content=b"x" * 1048577, headers=headers).status_code == 413
    with x["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(attempts)) == 0


def finish(x):
    receive(x)
    x["svc"].run_once()
    worker = ProcessWorker(x["svc"].store)
    for _ in range(5): assert worker.run_once()


def test_head_change_during_publication_prevents_success(github, monkeypatch):
    x = github
    finish(x)
    original = x["client"].pull
    calls = []
    def moved(number, token):
        calls.append(number)
        if len(calls) == 2:
            x["transport"].pr["head"]["sha"] = resolve(x["demo"], "pr/safe-refactor")
        return original(number, token)
    monkeypatch.setattr(x["client"], "pull", moved)
    x["svc"].run_once(publishing=True)
    assert "conclusion" not in x["transport"].remote_checks[0]
    with x["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(checks.c.state)) == "obsolete"


def test_missing_signing_evidence_cannot_publish_success(github):
    x = github
    finish(x)
    x["cfg"].signing_key_file = None
    x["svc"].run_once(publishing=True)
    assert "conclusion" not in x["transport"].remote_checks[0]
    with x["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(checks.c.state)) == "pending"


def test_forged_pass_with_unexecuted_mandatory_tests_is_failure(github):
    x = github
    x["transport"].pr["head"]["sha"] = resolve(x["demo"], "pr/safe-refactor")
    finish(x)
    with x["svc"].store.engine.begin() as c:
        result = c.scalar(sa.select(attempts.c.result))
        assert result["plan"]["mode"] != "NONE"
        result["verdict"] = "PASS"
        c.execute(attempts.update().values(result=result))
    x["svc"].run_once(publishing=True)
    assert x["transport"].remote_checks[0]["conclusion"] == "failure"


def test_concurrent_publishers_create_one_check(github):
    x = github
    receive(x)
    x["svc"].run_once()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: x["svc"].run_once(publishing=True), range(2)))
    assert len(x["transport"].remote_checks) == 1


def test_wrong_remote_check_identity_cannot_be_updated(github):
    x = github
    finish(x)
    with x["svc"].store.engine.connect() as c: aid = c.scalar(sa.select(checks.c.attempt_id))
    x["transport"].remote_checks.append({"id": 1, "external_id": "reposhield:" + aid, "app": {"id": 1},
        "head_sha": x["transport"].pr["head"]["sha"], "name": "wrong name"})
    x["svc"].run_once(publishing=True)
    assert not any(method == "PATCH" for method, _, _ in x["transport"].calls)


def test_merge_queue_and_installation_reactivation_events_do_not_schedule(github):
    x = github
    for event, action in (("merge_group", "checks_requested"), ("installation", "unsuspend")):
        raw = json.dumps({"installation": {"id": 2}, "action": action}).encode()
        assert x["svc"].receive(event, event, sign(SECRET, raw), raw)["state"] == "ignored"
    assert not x["svc"].run_once()


def test_fetch_command_is_public_bounded_and_has_no_credentials(github, monkeypatch):
    from reposhield.server.github_app import fetch_public
    from types import SimpleNamespace
    x = github
    calls = []
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[-1] == "--is-bare-repository": output = "true"
        elif cmd[-1] == "refs/reposhield/pr-1": output = x["transport"].pr["head"]["sha"]
        else: output = x["transport"].pr["base"]["sha"]
        return SimpleNamespace(returncode=0, stdout=output.encode())
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-inherit")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "99")
    monkeypatch.setattr("reposhield.server.github_app.subprocess.run", run)
    fetch_public({"path": x["demo"]}, x["client"].config, x["transport"].pr)
    serialized = str(calls)
    assert "must-not-inherit" not in serialized and "ephemeral-installation-test-token" not in serialized
    assert all("GIT_CONFIG_COUNT" not in kw["env"] and kw["timeout"] == 45 for _, kw in calls)
    assert any("https://github.com/demo/shop.git" in cmd for cmd, _ in calls)


def test_signed_ping_has_no_installation_requirement_or_job(github):
    raw = b'{"zen":"synthetic ping"}'
    assert github["svc"].receive("ping", "ping", sign(SECRET, raw), raw)["state"] == "ignored"
    with github["svc"].store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(deliveries)) == 0


def test_trusted_base_activation_changes_epoch(github, pg, monkeypatch):
    from reposhield.server.admin import main
    x = github
    monkeypatch.setenv("REPOSHIELD_DATABASE_URL", pg[1])
    before = x["svc"].store.repository("repo")
    main(["activate-base", "--id", "repo", "--base", "pr/docs-only"])
    after = x["svc"].store.repository("repo")
    assert after["base_sha"] == resolve(x["demo"], "pr/docs-only")
    assert after["policy_epoch"] == before["policy_epoch"] + 1


def test_failed_jobs_require_explicit_enabled_installation_to_retry(github, pg, monkeypatch):
    from reposhield.server.github_worker import main
    x = github
    receive(x)
    with x["svc"].store.engine.begin() as c:
        c.execute(deliveries.update().values(state="failed", tries=5))
    monkeypatch.setenv("REPOSHIELD_DATABASE_URL", pg[1])
    monkeypatch.setenv("REPOSHIELD_GITHUB_APP_CONFIG_FILE", x["cfg"].github_app_config_file)
    main(["--retry-failed"])
    with x["svc"].store.engine.begin() as c:
        assert c.scalar(sa.select(deliveries.c.state)) == "pending"
        assert c.scalar(sa.select(deliveries.c.tries)) == 0
        c.execute(installations.update().values(enabled=False))
    with pytest.raises(ValueError): main(["--retry-failed"])
