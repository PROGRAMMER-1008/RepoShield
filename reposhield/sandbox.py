"""Execution sandboxes for untrusted repository code.

SubprocessSandbox : DEV backend. POSIX: rlimits, scrubbed env, process-group kill, optional `unshare` net isolation.
                    Windows: scrubbed env, process-tree kill (taskkill) and timeouts only - no memory/CPU limits,
                    no network isolation. NOT a security boundary on any OS.
DockerSandbox     : hardened container (no network, read-only rootfs, dropped caps, no-new-privileges,
                    pid/mem/cpu limits, non-root). Not a perfect boundary either - see docs/SECURITY.md.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

IS_WINDOWS = os.name == "nt"
from dataclasses import dataclass, field, asdict


@dataclass
class Limits:
    timeout_seconds: int = 120
    memory_mb: int = 2048
    cpus: float = 2
    pids: int = 256
    max_output_bytes: int = 5 * 1024 * 1024
    max_file_mb: int = 256
    network: bool = False
    image: str = "reposhield-runner:py312"


@dataclass
class SandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False
    backend: str = ""
    isolation: dict = field(default_factory=dict)

    def to_dict(self, with_output: bool = False) -> dict:
        d = asdict(self)
        if not with_output:
            d["stdout"] = d["stdout"][-2000:]
            d["stderr"] = d["stderr"][-1000:]
        return d


def _read_capped(path: str, cap: int) -> tuple[str, bool]:
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        if size <= cap:
            return fh.read().decode("utf-8", "replace"), False
        head = fh.read(cap // 3)
        fh.seek(size - (cap - cap // 3))
        tail = fh.read()
    return head.decode("utf-8", "replace") + f"\n...[truncated {size - cap} bytes]...\n" + tail.decode("utf-8", "replace"), True


def _kill_tree(p) -> None:
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    else:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _exec(argv, cwd, env, limits: Limits, preexec=None, on_timeout=None) -> tuple[int | None, str, str, bool, bool, int]:
    tmp = tempfile.mkdtemp(prefix="rs-out-")
    out_p, err_p = os.path.join(tmp, "out"), os.path.join(tmp, "err")
    t0, timed_out = time.monotonic(), False
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WINDOWS else {"start_new_session": True, "preexec_fn": preexec}
    try:
        with open(out_p, "wb") as fo, open(err_p, "wb") as fe:
            p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, **kw)
            try:
                p.wait(timeout=limits.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                if on_timeout:
                    on_timeout()
                _kill_tree(p)
                p.wait()
            if not IS_WINDOWS:                     # reap stragglers left in the process group
                _kill_tree(p)
        out, t1 = _read_capped(out_p, limits.max_output_bytes)
        err, t2 = _read_capped(err_p, limits.max_output_bytes // 5)
        return p.returncode, out, err, timed_out, (t1 or t2), int((time.monotonic() - t0) * 1000)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def base_env(cwd: str, extra: dict | None = None, windows: bool = IS_WINDOWS) -> dict:
    """Scrubbed environment: no inherited secrets/tokens. Only what Python itself needs to start."""
    home = os.path.join(cwd, ".reposhield", "home")
    env = {"HOME": home, "TMPDIR": home, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
           "PYTHONPATH": os.path.join(cwd, ".reposhield", "plugins")}
    if windows:                                    # Python/winsock refuse to start without these
        for k in ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "PATHEXT", "COMSPEC"):
            if k in os.environ:
                env[k] = os.environ[k]
        env.update({"USERPROFILE": home, "TEMP": home, "TMP": home})
    else:
        env["PATH"] = os.pathsep.join([os.path.dirname(sys.executable), "/usr/local/bin", "/usr/bin", "/bin"])
    env.update(extra or {})
    return env


class SubprocessSandbox:
    name = "subprocess"
    python = sys.executable
    _net_ok: bool | None = None

    @classmethod
    def _can_unshare(cls) -> bool:
        if cls._net_ok is None:
            try:
                cls._net_ok = subprocess.run(["unshare", "--net", "--map-root-user", "true"],
                                             capture_output=True, timeout=5).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                cls._net_ok = False
        return cls._net_ok

    def isolation(self, limits: Limits) -> dict:
        net = (not limits.network) and not IS_WINDOWS and self._can_unshare()
        return {"backend": self.name, "security_boundary": False, "network_isolated": net,
                "rlimits": not IS_WINDOWS, "env_scrubbed": True, "platform": "windows" if IS_WINDOWS else "posix",
                "note": "dev backend - use docker for untrusted code" +
                        ("; Windows: no memory/CPU limits and no network isolation" if IS_WINDOWS else "")}

    def run(self, argv, cwd, env=None, limits: Limits | None = None) -> SandboxResult:
        limits = limits or Limits()
        resource = None
        if not IS_WINDOWS:
            import resource

        def preexec():
            if resource:
                mem = limits.memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
                cpu = limits.timeout_seconds + 5
                resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
                fs = limits.max_file_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_FSIZE, (fs, fs))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        os.makedirs(os.path.join(cwd, ".reposhield", "home"), exist_ok=True)
        env_all = base_env(cwd, env)
        iso = self.isolation(limits)
        cmd = list(argv)
        if iso["network_isolated"]:
            cmd = ["unshare", "--net", "--map-root-user", *cmd]
        code, out, err, to, trunc, ms = _exec(cmd, cwd, env_all, limits, preexec)
        return SandboxResult(code, out, err, ms, to, trunc, self.name, iso)


class DockerSandbox:
    name = "docker"
    python = "python"

    @staticmethod
    def available(image: str | None = None) -> bool:
        """Docker daemon reachable (and, if `image` is given, that image present locally)."""
        if not shutil.which("docker"):
            return False
        try:
            if subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode != 0:
                return False
            if image:
                return subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=10).returncode == 0
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False

    def isolation(self, limits: Limits) -> dict:
        return {"backend": self.name, "security_boundary": True, "network_isolated": not limits.network,
                "read_only_rootfs": True, "caps_dropped": True, "no_new_privileges": True,
                "pids_limit": limits.pids, "memory_mb": limits.memory_mb, "cpus": limits.cpus,
                "note": "container isolation; shares the host kernel"}

    def build_command(self, argv, workspace, env, limits: Limits, name: str) -> list[str]:
        cmd = ["docker", "run", "--rm", "--name", name,
               "--network", "bridge" if limits.network else "none",
               "--read-only", "--tmpfs", "/tmp:rw,exec,nosuid,size=256m",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--pids-limit", str(limits.pids),
               "--memory", f"{limits.memory_mb}m", "--memory-swap", f"{limits.memory_mb}m",
               "--cpus", str(limits.cpus),
               "--user", (f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "1000:1000"),
               "-v", f"{os.path.abspath(workspace)}:/workspace:rw", "-w", "/workspace",
               "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
               "-e", "PYTHONPATH=/workspace/.reposhield/plugins"]
        for k, v in (env or {}).items():
            cmd += ["-e", f"{k}={v}"]
        return cmd + [limits.image, *argv]

    def run(self, argv, cwd, env=None, limits: Limits | None = None) -> SandboxResult:
        limits = limits or Limits()
        name = f"reposhield-{uuid.uuid4().hex[:12]}"
        cmd = self.build_command(argv, cwd, env, limits, name)
        kill = lambda: subprocess.run(["docker", "kill", name], capture_output=True)
        code, out, err, to, trunc, ms = _exec(cmd, cwd, os.environ.copy(), limits, on_timeout=kill)
        return SandboxResult(code, out, err, ms, to, trunc, self.name, self.isolation(limits))


def pick_sandbox(name: str = "auto", image: str = Limits.image):
    """auto   = docker only if the daemon is up AND the runner image exists, otherwise the dev subprocess backend.
    docker = fail loudly (with the fix) instead of letting every test run die with a cryptic docker error."""
    if name == "docker":
        if not DockerSandbox.available():
            raise RuntimeError("docker backend requested, but Docker is not installed or its daemon is not running "
                               "(start Docker Desktop)")
        if not DockerSandbox.available(image):
            raise RuntimeError(f"docker runner image '{image}' not found. Build it:  "
                               f"docker build -t {image} -f runner/Dockerfile runner")
        return DockerSandbox()
    if name == "auto" and DockerSandbox.available(image):
        return DockerSandbox()
    return SubprocessSandbox()
