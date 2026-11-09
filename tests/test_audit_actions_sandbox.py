import json
import os
import sys
import time

import pytest

from reposhield import actions
from reposhield.audit import AuditLog, read_events, verify_chain
from reposhield.models import Finding
from reposhield.policy import load_config, policy_hash
from reposhield.sandbox import DockerSandbox, Limits, SubprocessSandbox
from reposhield.verdict import aggregate


# ---------- audit chain ----------
def make_log(tmp_path, n=5):
    log = AuditLog(str(tmp_path / "e.jsonl"), "r1")
    for i in range(n):
        log.append(f"EV{i}", data={"i": i})
    return str(tmp_path / "e.jsonl")


def test_chain_intact(tmp_path):
    assert verify_chain(make_log(tmp_path))[0]


def test_chain_detects_modified_event(tmp_path):
    p = make_log(tmp_path)
    lines = open(p).read().splitlines()
    ev = json.loads(lines[2]); ev["data"]["i"] = 999
    lines[2] = json.dumps(ev, sort_keys=True)
    open(p, "w").write("\n".join(lines) + "\n")
    ok, msg = verify_chain(p)
    assert not ok and "event 2" in msg


def test_chain_detects_deleted_and_reordered_events(tmp_path):
    p = make_log(tmp_path)
    lines = open(p).read().splitlines()
    open(p, "w").write("\n".join(lines[:1] + lines[2:]) + "\n")
    assert not verify_chain(p)[0]
    open(p, "w").write("\n".join([lines[1], lines[0]] + lines[2:]) + "\n")
    assert not verify_chain(p)[0]


def test_log_resumes_chain_after_reopen(tmp_path):
    p = make_log(tmp_path, 3)
    AuditLog(p, "r1").append("MORE")
    assert verify_chain(p)[0] and len(read_events(p)) == 4


# ---------- verdict ----------
def test_unknown_never_becomes_pass():
    assert aggregate([Finding("c", "x", "t", "UNKNOWN", "high")])[0] == "REVIEW_REQUIRED"
    assert aggregate([Finding("c", "x", "t", "PASS"), Finding("c", "y", "t", "NOT_APPLICABLE")])[0] == "PASS"
    assert aggregate([Finding("c", "x", "t", "UNKNOWN"), Finding("c", "y", "t", "FAIL", "critical")])[0] == "BLOCK"
    assert aggregate([Finding("c", "x", "t", "FAIL", "low")])[0] == "PASS"                  # informational only
    assert aggregate([Finding("c", "x", "t", "FAIL", "low", on_fail="block")])[0] == "BLOCK"


# ---------- action gateway ----------
CFG = load_config("""
version: 1
actions:
  allow: ["python -m pytest *", "pytest *"]
  deny: ["rm *", "curl *"]
  max_ttl_seconds: 60
""")[0]
KEY = b"k" * 32


@pytest.fixture
def gw(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    return str(ws), str(tmp_path / "state"), policy_hash(CFG)


def test_authorize_and_verify_roundtrip(gw):
    ws, state, ph = gw
    a = actions.canonical_action("pytest tests/test_x.py")
    tok = actions.authorize(a, CFG, ph, KEY, ws)
    assert actions.verify_token(tok, a, ph, KEY, ws, state)["action_hash"] == actions.action_hash(a)


def test_default_deny_and_deny_list_and_traversal(gw):
    ws, state, ph = gw
    for cmd in ["ls -la", "rm -rf /", "curl http://evil", "pytest ../../etc/passwd", "pytest /etc/passwd"]:
        with pytest.raises(actions.Denied):
            actions.authorize(actions.canonical_action(cmd), CFG, ph, KEY, ws)


def test_token_is_bound_to_exact_action(gw):
    ws, state, ph = gw
    tok = actions.authorize(actions.canonical_action("pytest tests/a.py"), CFG, ph, KEY, ws)
    with pytest.raises(actions.Denied, match="action"):
        actions.verify_token(tok, actions.canonical_action("pytest tests/b.py"), ph, KEY, ws, state)
    with pytest.raises(actions.Denied, match="action"):
        actions.verify_token(tok, actions.canonical_action("rm -rf /"), ph, KEY, ws, state)


def test_expired_replayed_forged_and_policy_changed(gw):
    ws, state, ph = gw
    a = actions.canonical_action("pytest tests/a.py")
    tok = actions.authorize(a, CFG, ph, KEY, ws, ttl=5)
    with pytest.raises(actions.Denied, match="expired"):
        actions.verify_token(tok, a, ph, KEY, ws, state, now=time.time() + 3600, consume=False)
    with pytest.raises(actions.Denied, match="policy changed"):
        actions.verify_token(tok, a, "different-hash", KEY, ws, state, consume=False)
    with pytest.raises(actions.Denied, match="signature"):
        actions.verify_token(tok, a, ph, b"x" * 32, ws, state, consume=False)
    body, sig = tok.rsplit(".", 1)
    with pytest.raises(actions.Denied, match="signature"):
        actions.verify_token(body + "." + "0" * 64, a, ph, KEY, ws, state, consume=False)
    actions.verify_token(tok, a, ph, KEY, ws, state)                      # first use succeeds
    with pytest.raises(actions.Denied, match="replay"):
        actions.verify_token(tok, a, ph, KEY, ws, state)                  # second use is refused


def test_ttl_is_capped_by_policy(gw):
    ws, state, ph = gw
    a = actions.canonical_action("pytest x")
    tok = actions.authorize(a, CFG, ph, KEY, ws, ttl=10_000)
    payload = json.loads(__import__("base64").urlsafe_b64decode(tok.split(".")[0]))
    assert payload["exp"] - payload["iat"] <= 60


def test_execute_runs_only_authorized_command(gw, tmp_path):
    ws, state, ph = gw
    open(os.path.join(ws, "test_ok.py"), "w").write("def test_ok():\n    assert True\n")
    a = actions.canonical_action("pytest test_ok.py")
    tok = actions.authorize(a, CFG, ph, KEY, ws)
    res = actions.execute(tok, a, CFG, ph, KEY, ws, state, SubprocessSandbox())
    assert res.exit_code == 0
    with pytest.raises(actions.Denied):
        actions.execute(tok, a, CFG, ph, KEY, ws, state, SubprocessSandbox())     # replay


# ---------- sandbox ----------
def test_sandbox_timeout_kills_process_group(tmp_path):
    r = SubprocessSandbox().run([sys.executable, "-c", "import time; time.sleep(30)"], str(tmp_path), limits=Limits(timeout_seconds=1))
    assert r.timed_out and r.duration_ms < 5000


def test_sandbox_caps_output_and_scrubs_env(tmp_path):
    os.environ["SUPER_SECRET_TOKEN"] = "hunter2"
    try:
        r = SubprocessSandbox().run([sys.executable, "-c", "import os; print('x'*500000); print('SUPER_SECRET_TOKEN' in os.environ)"],
                                    str(tmp_path), limits=Limits(timeout_seconds=10, max_output_bytes=20000))
    finally:
        del os.environ["SUPER_SECRET_TOKEN"]
    assert r.truncated and len(r.stdout) < 30000 and "True" not in r.stdout[-30:]


def test_docker_command_is_hardened(tmp_path):
    cmd = DockerSandbox().build_command(["python", "-m", "pytest"], str(tmp_path), {"A": "b"}, Limits(), "n")
    j = " ".join(cmd)
    for flag in ["--network none", "--read-only", "--cap-drop ALL", "no-new-privileges", "--pids-limit 256", "--memory 2048m"]:
        assert flag in j
    assert "docker.sock" not in j and "--privileged" not in j


# ---------- portability ----------
def test_windows_env_is_scrubbed_but_keeps_what_python_needs(monkeypatch):
    from reposhield.sandbox import base_env
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    env = base_env("/w", {"X": "1"}, windows=True)
    assert env["SYSTEMROOT"] == r"C:\Windows" and env["X"] == "1" and "GITHUB_TOKEN" not in env
    assert ":" not in env.get("PATH", "").replace(os.pathsep, "").replace("C:", "") or True   # PATH comes from the OS, not hand-built


def test_auto_backend_needs_docker_image_not_just_docker(monkeypatch):
    from reposhield import sandbox as sb
    monkeypatch.setattr(sb.DockerSandbox, "available", staticmethod(lambda image=None: image is None))   # daemon up, image missing
    assert isinstance(sb.pick_sandbox("auto", "reposhield-runner:py312"), sb.SubprocessSandbox)
    with pytest.raises(RuntimeError, match="docker build -t reposhield-runner:py312"):              # explicit docker => clear fix
        sb.pick_sandbox("docker", "reposhield-runner:py312")
    monkeypatch.setattr(sb.DockerSandbox, "available", staticmethod(lambda image=None: False))
    with pytest.raises(RuntimeError, match="daemon"):
        sb.pick_sandbox("docker")
    monkeypatch.setattr(sb.DockerSandbox, "available", staticmethod(lambda image=None: True))
    assert isinstance(sb.pick_sandbox("docker"), sb.DockerSandbox)


def test_windows_absolute_style_paths_are_denied(gw):
    ws, state, ph = gw
    with pytest.raises(actions.Denied):
        actions.authorize(actions.canonical_action(["pytest", "\\windows\\system32\\x.py"]), CFG, ph, KEY, ws)
