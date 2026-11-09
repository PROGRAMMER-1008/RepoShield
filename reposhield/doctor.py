"""`reposhield doctor`: check the environment and *prove* what the selected sandbox actually enforces."""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from .sandbox import DockerSandbox, Limits, SubprocessSandbox, pick_sandbox

PROBE = r"""
import json, os, sys
out = {"secret_visible": "RS_DOCTOR_SECRET" in os.environ, "uid": os.getuid() if hasattr(os, "getuid") else None}
try:
    import socket
    port = int(os.environ.get("RS_PROBE_PORT", "0"))
    if port:
        s = socket.create_connection(("127.0.0.1", port), timeout=2); s.close(); out["loopback_reachable"] = True
except Exception:
    out["loopback_reachable"] = False
try:
    out["interfaces"] = sorted(os.listdir("/sys/class/net"))
except Exception:
    out["interfaces"] = None
try:
    open("/rs_rootfs_probe", "w").close(); os.remove("/rs_rootfs_probe"); out["rootfs_writable"] = True
except Exception:
    out["rootfs_writable"] = False
print("PROBE" + json.dumps(out))
"""


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level: str, name: str, detail: str = ""):
        self.rows.append((level, name, detail))
        print(f"  [{level:^4}] {name:<30} {detail}")

    @property
    def failed(self) -> bool:
        return any(r[0] == "FAIL" for r in self.rows)


def _git_version() -> str | None:
    try:
        return subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def run_doctor(sandbox_name: str = "auto", image: str = Limits.image) -> int:
    r = Report()
    print(f"\nRepoShield doctor  ({platform.system()} {platform.release()})\n\nEnvironment")
    v = sys.version_info
    r.add("ok" if v >= (3, 10) else "FAIL", "python", f"{platform.python_version()}  {sys.executable}")
    g = _git_version()
    r.add("ok" if g else "FAIL", "git", g or "not found on PATH")
    for mod, need in (("yaml", True), ("pytest", True), ("coverage", False)):
        try:
            m = __import__(mod)
            r.add("ok", mod, getattr(m, "__version__", ""))
        except ImportError:
            r.add("FAIL" if need else "warn", mod,
                  "missing - `pip install -e \".[dev]\"`" if need else "missing - needed only for `reposhield baseline`")
    dock = shutil.which("docker")
    if not dock:
        r.add("warn", "docker", "not installed - dev sandbox only (no hardening)")
    elif not DockerSandbox.available():
        r.add("warn", "docker", "installed but the daemon is not running (start Docker Desktop)")
    elif not DockerSandbox.available(image):
        r.add("warn", "docker runner image", f"'{image}' not built:  docker build -t {image} -f runner/Dockerfile .")
    else:
        r.add("ok", "docker + runner image", image)

    try:
        sb = pick_sandbox(sandbox_name, image)
    except RuntimeError as e:
        print(f"\nSandbox self-test  (backend: {sandbox_name})")
        r.add("FAIL", "docker backend not ready", str(e))
        print("\nResult: PROBLEMS FOUND\n")
        return 1
    print(f"\nSandbox self-test  (backend: {sb.name})")
    lim = Limits(timeout_seconds=20, image=image)
    ws = tempfile.mkdtemp(prefix="rs-doctor-")
    srv = socket.socket()
    try:
        srv.bind(("127.0.0.1", 0)); srv.listen(5)
        port = srv.getsockname()[1]
        os.environ["RS_DOCTOR_SECRET"] = "host-secret"
        os.makedirs(os.path.join(ws, ".reposhield", "plugins"), exist_ok=True)
        res = sb.run([sb.python, "-c", PROBE], ws, env={"RS_PROBE_PORT": str(port)}, limits=lim)
        probe = None
        for line in res.stdout.splitlines():
            if line.startswith("PROBE"):
                probe = json.loads(line[5:])
        if probe is None:
            r.add("FAIL", "sandbox can run python", f"exit {res.exit_code}: {(res.stderr or res.stdout)[-160:].strip()}")
        else:
            r.add("ok", "sandbox can run python", f"{res.duration_ms} ms")
            r.add("FAIL" if probe["secret_visible"] else "ok", "host secrets hidden",
                  "tests can read host env vars!" if probe["secret_visible"] else "host environment variables are not visible to tests")
            ifaces = probe.get("interfaces")
            # /sys/class/net shows the *container's* interfaces under docker, but the host's under `unshare`,
            # so interfaces are only trusted for docker; otherwise use the loopback reachability probe.
            isolated = (ifaces == ["lo"]) if (sb.name == "docker" and ifaces is not None) else (not probe["loopback_reachable"])
            if sb.name == "docker":
                r.add("ok" if isolated else "FAIL", "network isolation", f"interfaces: {ifaces}")
                r.add("ok" if not probe["rootfs_writable"] else "FAIL", "read-only root filesystem", "")
                r.add("ok" if probe["uid"] != 0 else "warn", "non-root user", f"uid {probe['uid']}")
            else:
                r.add("ok" if isolated else "warn", "network isolation",
                      "loopback blocked" if isolated else "NOT isolated (expected on Windows/macOS or without `unshare`) - use docker")
        t0 = time.monotonic()
        tres = sb.run([sb.python, "-c", "import time; time.sleep(60)"], ws, limits=Limits(timeout_seconds=2, image=image))
        ok = tres.timed_out and (time.monotonic() - t0) < 15
        r.add("ok" if ok else "FAIL", "timeout kills runaway tests", f"stopped after {tres.duration_ms} ms" if ok else "process was not stopped")
        ores = sb.run([sb.python, "-c", "print('x' * 3_000_000)"], ws, limits=Limits(timeout_seconds=20, max_output_bytes=20000, image=image))
        r.add("ok" if ores.truncated and len(ores.stdout) < 40000 else "warn", "output flood is capped",
              f"kept {len(ores.stdout)} chars of 3,000,000")
    except Exception as e:                                           # a doctor must report, not crash
        r.add("FAIL", "sandbox self-test", f"{type(e).__name__}: {e}")
    finally:
        os.environ.pop("RS_DOCTOR_SECRET", None)
        srv.close()
        shutil.rmtree(ws, ignore_errors=True)
    iso = sb.isolation(lim)
    print(f"\nSecurity boundary: {'YES (container)' if iso.get('security_boundary') else 'NO - dev backend, do not run untrusted code with it'}")
    print(f"Result: {'PROBLEMS FOUND' if r.failed else 'ready'}\n")
    return 1 if r.failed else 0
