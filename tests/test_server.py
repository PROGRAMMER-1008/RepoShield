"""Phase 2 service: webhook -> queue -> verify -> GitHub reporting, REST API, dashboard, security properties."""
import json
import os
import pathlib
import re
import subprocess
import tempfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient                      # noqa: E402

from reposhield.audit import verify_chain                     # noqa: E402
from reposhield.server.app import create_app                  # noqa: E402
from reposhield.server.config import ServerConfig             # noqa: E402
from reposhield.server.db import Store                        # noqa: E402
from reposhield.server.github import GitHubClient, MARKER, sign, verify_signature   # noqa: E402
from reposhield.server.worker import _defang                  # noqa: E402

SECRET = "whsec-test"


class FakeGH:
    def __init__(self, comments=None):
        self.calls, self.comments = [], comments or []

    def __call__(self, method, url, headers, body):
        data = json.loads(body) if body else None
        self.calls.append((method, url.replace("https://api.github.com", ""), data))
        return (200, self.comments) if method == "GET" else (201, {"id": 1})

    def statuses(self):
        return [c[2]["state"] for c in self.calls if "/statuses/" in c[1]]


def sha_of(repo, ref):
    return subprocess.run(["git", "-C", repo, "rev-parse", ref], capture_output=True, text=True, check=True).stdout.strip()


def make(demo_repo, tmp_path, **kw):
    gh = FakeGH(kw.pop("comments", None))
    cfg = ServerConfig(data_dir=str(tmp_path / "data"), sandbox=kw.pop("sandbox", "subprocess"), webhook_secret=kw.pop("secret", SECRET),
                       allowed_repos=kw.pop("allowed", ["acme/payments"]), local_roots=kw.pop("roots", [os.path.dirname(demo_repo)]),
                       api_token=kw.pop("token", None), github_token="tkn", public_url="http://rs.test", **kw)
    app = create_app(cfg, start_workers=False, github=GitHubClient("tkn", transport=gh))
    return app, TestClient(app), gh


def pr_payload(demo_repo, branch, number=7, action="opened", name="acme/payments"):
    ref = f"refs/pull/{number}/head"
    subprocess.run(["git", "-C", demo_repo, "update-ref", ref, sha_of(demo_repo, branch)], check=True)
    return {"action": action, "number": number,
            "pull_request": {"number": number, "html_url": "http://x", "head": {"sha": sha_of(demo_repo, branch)},
                             "base": {"ref": "main"}},
            "repository": {"full_name": name, "clone_url": pathlib.Path(demo_repo).as_uri()}}


def post_hook(client, payload, delivery="d1", event="pull_request", secret=SECRET, sig=None):
    body = json.dumps(payload).encode()
    headers = {"x-github-event": event, "x-github-delivery": delivery,
               "x-hub-signature-256": sig or sign(secret, body), "content-type": "application/json"}
    return client.post("/webhooks/github", content=body, headers=headers)


# ---------------------------------------------------------------- signatures
def test_signature_verification():
    body = b'{"a":1}'
    assert verify_signature(SECRET, body, sign(SECRET, body))
    assert not verify_signature(SECRET, body, sign("other", body))
    assert not verify_signature(SECRET, body + b" ", sign(SECRET, body))
    assert not verify_signature(SECRET, body, None) and not verify_signature(SECRET, body, "sha1=abc")
    assert not verify_signature(None, body, sign(SECRET, body)) and not verify_signature("", body, sign("", body))


def test_webhook_rejects_forged_or_unconfigured(demo_repo, tmp_path):
    _, client, _ = make(demo_repo, tmp_path)
    p = pr_payload(demo_repo, "pr/docs-only")
    assert post_hook(client, p, sig="sha256=" + "0" * 64).status_code == 401
    assert post_hook(client, p, secret="wrong").status_code == 401
    _, client2, _ = make(demo_repo, tmp_path / "b", secret=None)
    assert post_hook(client2, p).status_code == 503                        # no secret configured => disabled, never open


def test_webhook_ping_ignored_events_and_allow_list(demo_repo, tmp_path):
    app, client, _ = make(demo_repo, tmp_path)
    assert post_hook(client, {}, event="ping").json() == {"ok": True}
    assert "ignored" in post_hook(client, {"x": 1}, event="push", delivery="d2").json()
    assert "ignored" in post_hook(client, pr_payload(demo_repo, "pr/docs-only", action="closed"), delivery="d3").json()
    assert post_hook(client, pr_payload(demo_repo, "pr/docs-only", name="evil/repo"), delivery="d4").status_code == 403
    bad = pr_payload(demo_repo, "pr/docs-only"); bad["pull_request"]["head"]["sha"] = "--upload-pack=x"
    assert "ignored" in post_hook(client, bad, delivery="d5").json()       # malformed sha never reaches git
    assert app.state.store.stats()["total"] == 0


# ---------------------------------------------------------------- end to end
def test_webhook_end_to_end_blocks_and_reports_to_github(demo_repo, tmp_path):
    app, client, gh = make(demo_repo, tmp_path)
    r = post_hook(client, pr_payload(demo_repo, "pr/analytics-leak"))
    assert r.status_code == 202
    rid = r.json()["id"]
    assert gh.statuses() == ["pending"]
    assert app.state.worker.run_pending() == 1
    row = client.get(f"/api/v1/runs/{rid}").json()
    assert row["run"]["status"] == "done" and row["run"]["verdict"] == "BLOCK"
    assert row["result"]["fingerprint"]["policy_source"].startswith("base:")
    assert gh.statuses() == ["pending", "failure"]
    status_call = [c for c in gh.calls if "/statuses/" in c[1]][-1]
    assert status_call[2]["context"] == "reposhield" and status_call[2]["target_url"] == f"http://rs.test/runs/{rid}"
    comment = [c for c in gh.calls if c[0] == "POST" and "/issues/7/comments" in c[1]][0][2]["body"]
    assert comment.startswith(MARKER) and "BLOCK" in comment and "payment-isolation" in comment
    audit = client.get(f"/api/v1/runs/{rid}/audit").json()
    assert audit["intact"] and audit["events"]
    rep = client.get(f"/api/v1/runs/{rid}/report")
    assert rep.status_code == 200 and "default-src 'none'" in rep.headers["content-security-policy"]


def test_duplicate_delivery_is_ignored_and_new_push_supersedes_queued_run(demo_repo, tmp_path):
    app, client, _ = make(demo_repo, tmp_path)
    first = post_hook(client, pr_payload(demo_repo, "pr/analytics-leak"), delivery="same").json()
    assert post_hook(client, pr_payload(demo_repo, "pr/analytics-leak"), delivery="same").json() == {"duplicate": True}
    second = post_hook(client, pr_payload(demo_repo, "pr/docs-only", action="synchronize"), delivery="other").json()
    assert app.state.store.get(first["id"])["status"] == "superseded"
    assert app.state.worker.run_pending() == 1                              # only the newest head is verified
    assert app.state.store.get(second["id"])["verdict"] == "PASS"


def test_untrusted_code_is_not_executed_without_an_isolating_sandbox(demo_repo, tmp_path):
    """Fail closed: a webhook-submitted PR must not run in the dev sandbox; it becomes REVIEW_REQUIRED, never PASS."""
    app, client, gh = make(demo_repo, tmp_path)
    rid = post_hook(client, pr_payload(demo_repo, "pr/safe-refactor")).json()["id"]
    app.state.worker.run_pending()
    run = client.get(f"/api/v1/runs/{rid}").json()
    assert run["run"]["verdict"] == "REVIEW_REQUIRED"
    assert run["result"]["tests"]["status"] == "NOT_RUN" and "NOT executed" in run["result"]["tests"]["reason"]
    assert any(f["rule_id"] == "tests-not-executed" for f in run["result"]["findings"])
    assert gh.statuses()[-1] == "failure"


def test_dev_sandbox_can_be_enabled_explicitly_for_local_experiments(demo_repo, tmp_path):
    app, client, _ = make(demo_repo, tmp_path, insecure_dev_sandbox=True)
    rid = post_hook(client, pr_payload(demo_repo, "pr/safe-refactor")).json()["id"]
    app.state.worker.run_pending()
    run = client.get(f"/api/v1/runs/{rid}").json()
    assert run["run"]["verdict"] == "PASS" and run["result"]["tests"]["status"] == "RAN"


def test_failed_run_is_reported_as_error_never_green(demo_repo, tmp_path):
    app, client, gh = make(demo_repo, tmp_path)
    p = pr_payload(demo_repo, "pr/docs-only")
    p["repository"]["clone_url"] = pathlib.Path(tmp_path / "does-not-exist").as_uri()
    rid = post_hook(client, p).json()["id"]
    app.state.worker.run_pending()
    assert app.state.store.get(rid)["status"] == "error"
    assert gh.statuses() == ["pending", "error"]


def test_existing_comment_is_updated_not_duplicated(demo_repo, tmp_path):
    app, client, gh = make(demo_repo, tmp_path, comments=[{"id": 99, "body": MARKER + "\nold"}])
    post_hook(client, pr_payload(demo_repo, "pr/analytics-leak"))
    app.state.worker.run_pending()
    assert any(c[0] == "PATCH" and c[1].endswith("/issues/comments/99") for c in gh.calls)
    assert not any(c[0] == "POST" and "/issues/7/comments" in c[1] for c in gh.calls)


def test_comment_text_cannot_ping_users():
    assert "@" not in _defang("path/@everyone.py").replace("@\u200b", "")


# ---------------------------------------------------------------- local API
def test_local_verification_via_api(demo_repo, tmp_path):
    app, client, _ = make(demo_repo, tmp_path)
    r = client.post("/api/v1/verify", json={"repo_path": demo_repo, "base": "main", "head": "pr/docs-only"})
    assert r.status_code == 202
    app.state.worker.run_pending()
    got = client.get(f"/api/v1/runs/{r.json()['id']}").json()
    assert got["run"]["verdict"] == "PASS" and got["result"]["verdict"] == "PASS"


def test_local_verification_is_confined_and_validated(demo_repo, tmp_path):
    app, client, _ = make(demo_repo, tmp_path)
    post = lambda **b: client.post("/api/v1/verify", json=b)
    assert post(repo_path=tempfile.gettempdir() + "/../../etc").status_code == 403           # outside allowed roots
    plain = pathlib.Path(demo_repo).parent / "plain"; plain.mkdir(exist_ok=True)
    assert post(repo_path=str(plain)).status_code == 422                                      # not a git repo
    for bad in ("--output=/tmp/x", "a b", "main..HEAD", "$(id)"):
        assert post(repo_path=demo_repo, head=bad).status_code == 422, bad                    # no option/shell injection via refs
    assert client.post("/api/v1/verify", json={}).status_code == 422
    _, off, _ = make(demo_repo, tmp_path / "x", roots=[])
    assert off.post("/api/v1/verify", json={"repo_path": demo_repo}).status_code == 403       # disabled unless --allow-local


# ---------------------------------------------------------------- auth
def test_api_token_protects_everything_but_health_and_signed_webhooks(demo_repo, tmp_path):
    app, client, _ = make(demo_repo, tmp_path, token="s3cr3t-token")
    assert client.get("/api/v1/health").status_code == 200
    for path in ("/", "/api/v1/runs", "/runs/abc"):
        assert client.get(path).status_code == 401
    assert client.post("/api/v1/verify", json={"repo_path": demo_repo}).status_code == 401
    assert client.get("/api/v1/runs", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/v1/runs", headers={"Authorization": "Bearer s3cr3t-token"}).status_code == 200
    import base64
    basic = base64.b64encode(b"anyone:s3cr3t-token").decode()
    assert client.get("/", headers={"Authorization": f"Basic {basic}"}).status_code == 200
    assert post_hook(client, {}, event="ping").status_code == 200                             # webhook uses its own signature


# ---------------------------------------------------------------- dashboard
def test_dashboard_escapes_untrusted_strings_and_sets_csp(demo_repo, tmp_path):
    app, client, _ = make(demo_repo, tmp_path)
    store = app.state.store
    rid = store.create_run(source="github", repo="x/<script>alert(1)</script>", base="main", head="a" * 40, pr_number=3, supersede=False)
    store.claim_next()
    store.finish(rid, verdict="BLOCK", summary="<img src=x onerror=alert(2)>", run_id="rs_x", run_dir=str(tmp_path), tests={})
    page = client.get("/")
    assert "<script>alert(1)" not in page.text and "&lt;script&gt;" in page.text
    assert "<img src=x" not in page.text and "&lt;img" in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert client.get(f"/runs/{rid}").status_code == 200


def test_ui_form_requires_csrf_token(demo_repo, tmp_path):
    app, client, _ = make(demo_repo, tmp_path)
    page = client.get("/").text
    token = re.search(r"name=csrf value='([0-9a-f]+)'", page).group(1)
    data = {"repo_path": demo_repo, "base": "main", "head": "pr/docs-only"}
    assert client.post("/ui/verify", data={**data, "csrf": "forged"}, follow_redirects=False).status_code == 403
    ok = client.post("/ui/verify", data={**data, "csrf": token}, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"].startswith("/runs/")
    app.state.worker.run_pending()
    assert "PASS" in client.get(ok.headers["location"]).text


# ---------------------------------------------------------------- store
def test_store_claims_each_job_once_and_recovers_after_crash(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    a = s.create_run(source="local", repo="r", base="main", head="x", supersede=False)
    b = s.create_run(source="local", repo="r", base="main", head="y", supersede=False)
    first, second = s.claim_next(), s.claim_next()
    assert {first["id"], second["id"]} == {a, b} and s.claim_next() is None
    assert s.recover_interrupted() == 2                                   # server died mid-run => both go back to the queue
    assert s.claim_next() is not None


def test_serve_command_refuses_public_bind_without_token(monkeypatch, capsys):
    from reposhield.cli import main
    monkeypatch.delenv("REPOSHIELD_API_TOKEN", raising=False)
    assert main(["serve", "--host", "0.0.0.0"]) == 3
    assert "non-loopback" in capsys.readouterr().err
