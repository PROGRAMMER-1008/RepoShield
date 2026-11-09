import json
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from alembic import command

from reposhield.action_policy import Resource, Scope, evaluate, patch_paths
from reposhield.contracts import ActionRequest
from reposhield.server.action_service import ActionService
from reposhield.server.app import create_app
from reposhield.server.config import ServerConfig
from reposhield.server.admin import migration_config
from reposhield.server.identities import Identity
from reposhield.server.schema_v1 import decisions, repositories, sessions, events
from reposhield.server.schema_v2 import approvals
from tests.test_durable import pg, registered


PATHS = ("src/app.py", "tests/test_app.py", "docs/guide.md")
SCOPE = dict(actions=["READ_FILE", "APPLY_PATCH", "RUN_TESTS"], paths=list(PATHS),
             profiles=["isolated-python"], max_bytes=65536)
REVISION = "sha256:" + "a" * 64


def resource():
    return Resource(resource_id="source", tenant_id="tenant", repository_id="repo",
        workspace_revision=REVISION, policy_epoch=1, administrator=SCOPE, repository=SCOPE,
        sessions={"agent": SCOPE, "reviewer": SCOPE})


def request(action, sid="session"):
    return ActionRequest(schema_version=2, tenant_id="tenant", repository_id="repo",
                         session_id=sid, workspace_revision=REVISION, action=action)


def patch(path="src/app.py"):
    return {"action_type": "APPLY_PATCH", "patch": f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"}


def actor(name="agent", role=None):
    return Identity(id=name, role=role or name, tenant_id="tenant", repository_ids=["repo"], token_sha256="0"*64)


@pytest.mark.parametrize("action", [{"action_type": "READ_FILE", "path": PATHS[0]}, patch(),
    {"action_type": "RUN_TESTS", "test_paths": [PATHS[1]], "profile": "isolated-python"}])
def test_permitted_actions_are_allowed(action):
    assert evaluate(request(action), resource(), Scope(**SCOPE))["decision"] == "ALLOW"


@pytest.mark.parametrize("kind", ["DATABASE_OPERATION", "NETWORK_REQUEST", "EXECUTE_COMMAND"])
def test_unsupported_actions_cannot_be_granted(kind):
    assert evaluate(request({"action_type": kind, "resource_id": "production"}),
                    resource(), Scope(**SCOPE))["decision"] == "DENY"


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "C:/secret", "src\\app.py", "src/app.py:stream",
    "src/../app.py", ".reposhield.yml", ".git/config", "src/CON", "src/app.py.", "https://example.org"])
def test_path_spelling_cannot_escape(path):
    result = evaluate(request({"action_type": "READ_FILE", "path": path}), resource(), Scope(**SCOPE))
    assert result["decision"] == "DENY"


@pytest.mark.parametrize("layer", ["administrator", "repository", "session"])
def test_each_scope_can_deny_and_repository_cannot_enlarge(layer):
    r, scope = resource(), Scope(**SCOPE)
    if layer == "session":
        scope = Scope()
    else:
        r = r.model_copy(update={layer: Scope()})
    assert evaluate(request(patch()), r, scope)["decision"] == "DENY"


def test_profile_size_snapshot_and_capability_denials():
    r, scope = resource(), Scope(**SCOPE)
    for req in [request({"action_type": "RUN_TESTS", "test_paths": [PATHS[1]], "profile": "host-shell"}),
                request({"action_type": "READ_FILE", "path": PATHS[0], "max_bytes": 65537}),
                request(patch()).model_copy(update={"workspace_revision": "sha256:" + "b"*64}),
                request(patch()).model_copy(update={"requested_capabilities": ("production",)})]:
        assert evaluate(req, r, scope)["decision"] == "DENY"


@pytest.mark.parametrize("text", ["diff --git a/x b/x\n", "--- /dev/null\n+++ b/x\n", 
    "--- a/src/app.py\n+++ b/docs/guide.md\n@@ -1 +1 @@\n-a\n+b\n",
    "--- a/src/app.py\n+++ b/src/app.py\n@@ -1,2 +1 @@\n-a\n+b\n",
    "--- a/src/app.py\n+++ b/src/app.py\nold mode 100644\nnew mode 120000\n"])
def test_ambiguous_or_incomplete_patches_deny(text):
    assert evaluate(request({"action_type": "APPLY_PATCH", "patch": text}), resource(), Scope(**SCOPE))["decision"] == "DENY"


def test_only_document_patch_is_reviewable():
    assert evaluate(request(patch("docs/guide.md")), resource(), Scope(**SCOPE))["decision"] == "REVIEW_REQUIRED"
    mixed = patch("docs/guide.md")["patch"] + patch()["patch"]
    assert evaluate(request({"action_type": "APPLY_PATCH", "patch": mixed}), resource(), Scope(**SCOPE))["decision"] == "DENY"


@pytest.fixture
def service(registered, tmp_path):
    path = tmp_path / "trusted-policy.json"
    path.write_text(json.dumps({"schema_version": 1, "resources": [resource().model_dump(mode="json")]}))
    svc = ActionService(registered, str(path))
    sid = registered.create_session("repo", "agent", action_scope=svc.scope_for("repo", "agent"))
    return svc, sid, path


def test_persisted_approval_keeps_raw_decision_and_is_idempotent(service):
    svc, sid, _ = service
    result = svc.authorize(request(patch("docs/guide.md"), sid), actor())
    assert result["decision"] == "REVIEW_REQUIRED"
    def approve(_):
        return svc.approve(result["id"], actor("reviewer"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(r["approved"] for r in pool.map(approve, range(2)))
    with svc.store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(approvals)) == 1
        assert c.scalar(sa.select(decisions.c.decision)) == "REVIEW_REQUIRED"
        assert c.scalar(sa.select(sa.func.count()).select_from(events).where(events.c.kind == "ACTION_APPROVED")) == 1


@pytest.mark.parametrize("change", ["policy", "snapshot", "epoch", "expire", "revoke"])
def test_approval_invalidated_by_context_changes(service, change):
    svc, sid, path = service
    result = svc.authorize(request(patch("docs/guide.md"), sid), actor())
    if change in ("policy", "snapshot"):
        data = json.loads(path.read_text())
        if change == "policy":
            data["resources"][0]["administrator"]["actions"] = []
        else:
            data["resources"][0]["workspace_revision"] = "sha256:" + "b"*64
        path.write_text(json.dumps(data))
    else:
        with svc.store.engine.begin() as c:
            if change == "epoch":
                c.execute(repositories.update().values(policy_epoch=2))
            elif change == "expire":
                c.execute(decisions.update().values(expires_at=sa.func.clock_timestamp()))
            else:
                c.execute(sessions.update().values(state="revoked"))
    with pytest.raises(HTTPException) as exc:
        svc.approve(result["id"], actor("reviewer"))
    assert exc.value.status_code in (403, 409)
    with svc.store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(approvals)) == 0


def test_hard_denials_and_agent_self_approval_rejected(service):
    svc, sid, _ = service
    denial = svc.authorize(request({"action_type": "DATABASE_OPERATION", "resource_id": "prod"}, sid), actor())
    assert denial["decision"] == "DENY"
    with pytest.raises(HTTPException, match="") as e:
        svc.approve(denial["id"], actor("reviewer"))
    assert e.value.status_code == 409
    review = svc.authorize(request(patch("docs/guide.md"), sid), actor())
    for identity in (actor(), actor("agent", "administrator"), actor("reviewer").model_copy(update={"repository_ids": []})):
        with pytest.raises(HTTPException) as e:
            svc.approve(review["id"], identity)
        assert e.value.status_code in (403, 404)


def test_missing_scope_cannot_be_enlarged_after_session_creation(service):
    svc, _, path = service
    sid = svc.store.create_session("repo", "agent", action_scope=Scope().model_dump(mode="json"))
    assert svc.authorize(request(patch(), sid), actor())["decision"] == "DENY"
    # Even the administrator updating the file cannot retrospectively enlarge this session.
    assert svc.scope_for("repo", "agent")["actions"]
    assert svc.authorize(request(patch(), sid), actor())["reason"] == "action_outside_intersection"


def test_untrusted_policy_location_and_malformed_policy_fail_closed(service, demo_repo):
    svc, sid, path = service
    with svc.store.engine.begin() as c:
        c.execute(repositories.update().values(path=str(path.parent)))
    with pytest.raises(HTTPException) as e:
        svc.authorize(request(patch(), sid), actor())
    assert e.value.status_code == 503
    with svc.store.engine.begin() as c:
        c.execute(repositories.update().values(path=str(demo_repo)))
    path.write_text('{"schema_version":1,"resources":[')
    with pytest.raises(HTTPException) as e:
        svc.authorize(request(patch(), sid), actor())
    assert e.value.status_code == 503
    with svc.store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(decisions)) == 0


def test_narrowing_current_session_grant_takes_effect(service):
    svc, sid, path = service
    assert svc.authorize(request(patch(), sid), actor())["decision"] == "ALLOW"
    data = json.loads(path.read_text())
    data["resources"][0]["sessions"]["agent"]["paths"] = []
    path.write_text(json.dumps(data))
    assert svc.authorize(request(patch(), sid), actor())["decision"] == "DENY"


def test_decision_event_failure_rolls_back_everything(service, monkeypatch):
    svc, sid, _ = service
    def fail(*args, **kwargs):
        raise RuntimeError("injected event failure")
    monkeypatch.setattr(svc.store, "_event", fail)
    with pytest.raises(RuntimeError):
        svc.authorize(request(patch(), sid), actor())
    from reposhield.server.schema_v1 import action_requests
    with svc.store.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(decisions)) == 0
        assert c.scalar(sa.select(sa.func.count()).select_from(action_requests)) == 0


def test_migration_upgrade_preserves_registered_repositories(registered, pg):
    command.downgrade(migration_config(pg[1]), "0001")
    assert registered.repository("repo")["tenant_id"] == "tenant"
    command.upgrade(migration_config(pg[1]), "head")
    registered.check_schema()
    assert registered.repository("repo")["tenant_id"] == "tenant"


def test_http_authorize_inspect_approve_and_no_execution(service, pg, tmp_path):
    svc, _, policy_path = service
    identities = []
    for name, role, repos in [("agent", "agent", ["repo"]), ("agent2", "agent", ["repo"]),
                              ("reviewer", "reviewer", ["repo"]), ("viewer", "viewer", ["repo"]),
                              ("outsider", "reviewer", ["other"])]:
        identities.append(dict(id=name, role=role, tenant_id="tenant", repository_ids=repos,
                               token_sha256=hashlib.sha256(name.encode()).hexdigest()))
    identity_path = tmp_path / "identities.json"
    identity_path.write_text(json.dumps(identities))
    cfg = ServerConfig(database_url=pg[1], identities_file=str(identity_path), action_policy_file=str(policy_path))
    def headers(who="agent"):
        return {"Authorization": "Bearer " + who}
    with TestClient(create_app(cfg)) as client:
        sid = client.post("/api/v1/sessions", json={"repository_id": "repo"}, headers=headers()).json()["id"]
        url = "/api/v1/actions/authorize"
        body = request(patch("docs/guide.md"), sid).model_dump(mode="json")
        assert client.post(url, json=body).status_code == 401
        assert client.post(url, json=body, headers=headers("agent2")).status_code == 403
        result = client.post(url, json=body, headers=headers()).json()
        assert result["decision"] == "REVIEW_REQUIRED" and not result["execution_enabled"]
        detail = "/api/v1/actions/" + result["id"]
        assert client.get(detail, headers=headers("outsider")).status_code == 404
        assert client.get(detail, headers=headers("agent2")).status_code == 403
        inspected = client.get(detail, headers=headers("reviewer")).json()
        assert inspected["request"] == body and inspected["approval"] is None
        assert client.post(detail + "/approve", headers=headers()).status_code == 403
        assert client.post(detail + "/approve", headers=headers("viewer")).status_code == 403
        assert client.post(detail + "/approve", headers=headers("reviewer")).json()["approved"]
        inspected = client.get(detail, headers=headers("reviewer")).json()
        assert inspected["decision"]["decision"] == "REVIEW_REQUIRED"
        assert inspected["approval"]["actor_id"] == "reviewer"
        assert client.post("/api/v1/actions/execute", headers=headers()).status_code == 501
        for action in [{"action_type": "READ_FILE", "path": PATHS[0]}, patch(),
                       {"action_type": "RUN_TESTS", "test_paths": [PATHS[1]], "profile": "isolated-python"}]:
            allowed = client.post(url, json=request(action, sid).model_dump(mode="json"), headers=headers()).json()
            assert allowed["decision"] == "ALLOW" and not allowed["execution_enabled"]
        denied = client.post(url, json=request({"action_type": "NETWORK_REQUEST", "resource_id": "internet"}, sid)
                             .model_dump(mode="json"), headers=headers()).json()
        assert denied["decision"] == "DENY"
        assert client.post("/api/v1/actions/" + denied["id"] + "/approve", headers=headers("reviewer")).status_code == 409
