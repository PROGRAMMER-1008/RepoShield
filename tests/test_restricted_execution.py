import json
import os
from pathlib import Path
import subprocess
import sys
import time
import io
import zipfile

import pytest

from reposhield.authorization import ExecutionProfile
from reposhield.snapshots import SnapshotStore, apply_patch, encode_snapshot, decode_snapshot
from reposhield.restricted_runner import RestrictedRunner, RunnerFailure


def profile(**kw):
    image = os.environ.get("REPOSHIELD_TEST_RUNNER_IMAGE")
    if not image:
        pytest.skip("Set REPOSHIELD_TEST_RUNNER_IMAGE to the real built image identity")
    return ExecutionProfile(**{**dict(image=image, executor_audience="broker", timeout_seconds=15,
        memory_mb=128, cpu_millis=500, pids=32, disk_mb=8, output_bytes=65536, uid=1000), **kw})


def test_snapshot_patch_is_content_addressed_and_old_bytes_unchanged(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots")
    original = {"src/app.py": b"old\n", "tests/test_app.py": b"def test_it(): assert True\n"}
    revision = store.put(original)
    patched = apply_patch(original, "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n")
    new_revision = store.put(patched)
    assert revision != new_revision and store.get(revision) == original
    assert store.get(new_revision)["src/app.py"] == b"new\n"
    assert store.put(original) == revision
    (store.root / (revision[7:] + ".json")).write_bytes(encode_snapshot(patched))
    with pytest.raises(ValueError, match="integrity"): store.get(revision)


@pytest.mark.parametrize("path", ["../x", "/etc/passwd", ".git/config", "x/../y", "C:/x", "x\\y"])
def test_snapshot_rejects_unsafe_paths(path):
    with pytest.raises(ValueError): encode_snapshot({path: b"data"})


def test_patch_rejects_wrong_context_and_snapshot_rejects_noncanonical_data():
    with pytest.raises(ValueError, match="context"):
        apply_patch({"x.py": b"different\n"}, "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n")
    with pytest.raises(ValueError): decode_snapshot(b'{"version":1,"files":{"x":"YQ=="},"extra":1}')
    with pytest.raises(ValueError): encode_snapshot({"a": b"x", "a/b": b"y"})


ISOLATION = b'''
import os,pathlib,socket
def test_isolation():
    assert os.getuid()==1000
    assert not pathlib.Path('/var/run/docker.sock').exists()
    assert not pathlib.Path('/host').exists()
    assert 'REPOSHIELD_DATABASE_URL' not in os.environ
    assert 'REPOSHIELD_SIGNING_KEY_FILE' not in os.environ
    status=pathlib.Path('/proc/self/status').read_text()
    assert 'CapEff:\\t0000000000000000' in status
    assert 'NoNewPrivs:\\t1' in status
    assert 'Seccomp:\\t2' in status
    assert pathlib.Path('/sys/fs/cgroup/pids.max').read_text().strip()=='32'
    assert pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip()=='134217728'
    assert pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().split()[0]=='50000'
    try: pathlib.Path('/opt/forbidden').write_text('no')
    except OSError: pass
    else: assert False, 'writable root'
    s=socket.socket(); s.settimeout(0.2)
    try: s.connect(('192.0.2.1',443))
    except OSError: pass
    else: assert False, 'network reachable'
    finally: s.close()
    pathlib.Path('test_probe.py').write_text('changed only isolated copy')
'''


@pytest.fixture
def runner():
    p = profile()
    value = RestrictedRunner(development_desktop=True)
    yield value
    assert value.command(["ps", "-a", "--filter", "label=reposhield.restricted=true", "--format", "{{.Names}}"]).strip() == b""


def test_real_linux_isolation_and_original_snapshot_unchanged(runner, tmp_path):
    p = profile()
    store = SnapshotStore(tmp_path / "source")
    revision = store.put({"test_probe.py": ISOLATION})
    result = runner.run(store.get(revision), ["test_probe.py"], p)
    assert result["mandatory_evidence_satisfied"], result
    assert result["mode"] == "DEVELOPMENT EXECUTION"
    assert store.get(revision) == {"test_probe.py": ISOLATION}
    actual = result["isolation"]
    assert actual["ReadonlyRootfs"] and actual["NetworkMode"] == "none"
    assert not actual["Binds"] and not actual.get("VolumesFrom")
    assert actual["MemorySwap"] == actual["Memory"]
    evidence_dir = os.environ.get("REPOSHIELD_TEST_EVIDENCE_DIR")
    if evidence_dir: Path(evidence_dir, "real-isolation.json").write_text(json.dumps(result, indent=2))


@pytest.mark.parametrize("code", [b'import pytest\n@pytest.mark.skip\ndef test_skip(): pass\n',
    b'import pytest\n@pytest.mark.xfail\ndef test_xpass(): pass\n',
    b'import pytest\n@pytest.mark.xfail\ndef test_xfail(): assert False\n',
    b'def test_fail(): assert False\n', b'x=1\n', b'import nonexistent_dependency_rs206\n'])
def test_missing_or_failing_evidence_never_satisfies_tests(runner, code):
    result = runner.run({"test_probe.py": code}, ["test_probe.py"], profile())
    assert result["mandatory_evidence_satisfied"] is False


@pytest.mark.parametrize("code,limits", [
    (b'import time\ndef test_long(): time.sleep(60)\n', {"timeout_seconds": 3}),
    (b'def test_memory(): x=bytearray(512*1024*1024)\n', {"memory_mb": 64}),
    (b'import os\ndef test_output():\n f=os.open("/proc/1/fd/1",os.O_WRONLY); os.write(f,b"x"*1048576)\n', {}),
])
def test_real_timeout_memory_output_failure_cleans_container(runner, code, limits):
    with pytest.raises(RunnerFailure): runner.run({"test_probe.py": code}, ["test_probe.py"], profile(**limits))


def test_real_disk_and_pid_limits(runner):
    code = b'''
import os,subprocess
def test_disk():
    try:
        with open('/work/large','wb') as f: f.write(b'x'*16*1024*1024)
    except OSError: pass
    else: assert False
    finally: os.unlink('/work/large')
def test_pids():
    children=[]
    try:
        for _ in range(40): children.append(subprocess.Popen(['sleep','20']))
    except OSError: pass
    else: assert False
    finally:
        for p in children: p.kill(); p.wait()
'''
    result = runner.run({"test_probe.py": code}, ["test_probe.py"], profile())
    assert result["mandatory_evidence_satisfied"], result


def test_revocation_during_run_removes_container(runner):
    start = time.monotonic()
    with pytest.raises(RunnerFailure, match="session_inactive"):
        runner.run({"test_probe.py": b'import time\ndef test_it(): time.sleep(60)\n'}, ["test_probe.py"],
                   profile(), lambda: time.monotonic() - start < 2)


def test_missing_image_fails_closed(runner):
    with pytest.raises(RunnerFailure): runner.preflight(profile(image="missing@sha256:" + "0"*64))


def test_desktop_is_not_dedicated_linux_acceptance():
    runner = RestrictedRunner()
    p = profile()
    info = json.loads(runner.command(["info", "--format", "{{json .}} "]))
    if "desktop" not in info.get("OperatingSystem", "").lower():
        pytest.skip("desktop-specific negative test")
    with pytest.raises(RunnerFailure, match="dedicated_linux"): runner.preflight(p)


def test_dependency_preparation_occurs_inside_isolated_copy(runner):
    wheel = io.BytesIO()
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("probe_dep/__init__.py", "import os\nassert 'REPOSHIELD_DATABASE_URL' not in os.environ\nVALUE=7\n")
        z.writestr("probe_dep-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: probe-dep\nVersion: 1.0\n")
        z.writestr("probe_dep-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr("probe_dep-1.0.dist-info/RECORD", "")
    files = {"requirements.txt": b"probe-dep==1.0\n", "wheels/probe_dep-1.0-py3-none-any.whl": wheel.getvalue(),
             "test_probe.py": b"from probe_dep import VALUE\ndef test_dep(): assert VALUE==7\n"}
    result = runner.run(files, ["test_probe.py"], profile())
    assert result["mandatory_evidence_satisfied"], result
    import importlib.util
    assert importlib.util.find_spec("probe_dep") is None


def test_missing_offline_dependency_is_non_successful(runner):
    with pytest.raises(RunnerFailure):
        runner.run({"requirements.txt": b"nonexistent-reposhield-dependency==1.0\n",
                    "test_probe.py": b"def test_it(): assert True\n"}, ["test_probe.py"], profile())


def test_independent_watchdog_cleans_container_after_broker_crash(runner):
    from reposhield.runner_watchdog import reap_expired
    p = profile(timeout_seconds=4)
    script = '''
import json,sys
from reposhield.authorization import ExecutionProfile
from reposhield.restricted_runner import RestrictedRunner
RestrictedRunner(development_desktop=True).run(
    {'test_probe.py': b'import time\\ndef test_long(): time.sleep(60)\\n'},
    ['test_probe.py'], ExecutionProfile.model_validate(json.loads(sys.argv[1])))
'''
    process = subprocess.Popen([sys.executable, "-c", script, p.model_dump_json()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        ids = b""
        while time.monotonic() < deadline and not ids:
            ids = runner.command(["ps", "-q", "--filter", "label=reposhield.restricted=true"]).strip()
            time.sleep(0.1)
        assert ids
        process.kill()  # no finally block; the independent watchdog must remove it
        process.wait(timeout=5)
        removed = []
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not removed:
            removed = reap_expired(runner)
            time.sleep(0.1)
        assert len(removed) == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for container_id in ids.decode().split():
            subprocess.run([runner.docker, "rm", "-f", container_id], capture_output=True, timeout=10)
