"""Docker execution adapter with bounded pipes, no mounts, and unconditional removal."""
import base64
import json
import os
import platform
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET


class RunnerFailure(RuntimeError):
    pass


def test_evidence(observation, paths):
    """Treat captured pytest XML as hostile observations, never verification PASS."""
    xml = observation.get("junit", "")
    if not isinstance(xml, str) or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise RunnerFailure("invalid_test_report")
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, ValueError):
        raise RunnerFailure("invalid_test_report") from None
    cases = list(root.iter("testcase"))
    passed = {c.get("file") for c in cases if not any(c.find(tag) is not None for tag in ("failure", "error", "skipped"))}
    complete = observation.get("exit_code") == 0 and bool(cases) and all(p in passed for p in paths)
    complete = complete and not any(c.find(tag) is not None for c in cases for tag in ("failure", "error"))
    observed = observation.get("files")
    if not isinstance(observed, dict): raise RunnerFailure("missing_observations")
    for counts in observed.values():
        if (not isinstance(counts, dict) or set(counts) != {"passed", "failed"}
                or any(type(v) is not int or v < 0 for v in counts.values())):
            raise RunnerFailure("invalid_observations")
    complete = complete and all(observed.get(p, {}).get("passed", 0) > 0 for p in paths)
    complete = complete and not any(counts["failed"] for counts in observed.values())
    return {"mandatory_evidence_satisfied": complete, "observed_cases": len(cases),
            "exit_code": observation.get("exit_code"), "stdout": observation.get("stdout", ""), "junit": xml}


class RestrictedRunner:
    def __init__(self, *, development_desktop=False, docker="docker"):
        self.development_desktop, self.docker = development_desktop, docker

    def command(self, args, timeout=20):
        result = subprocess.run([self.docker, *args], capture_output=True, timeout=timeout)
        if result.returncode:
            raise RunnerFailure("docker_control_failed")
        return result.stdout

    def preflight(self, profile):
        info = json.loads(self.command(["info", "--format", "{{json .}} "]))
        if info.get("OSType") != "linux":
            raise RunnerFailure("linux_containers_required")
        if not self.development_desktop and (platform.system() != "Linux" or "desktop" in info.get("OperatingSystem", "").lower()):
            raise RunnerFailure("dedicated_linux_host_required")
        # Local immutable image-config digest, not a mutable tag or automatic pull.
        image_id = profile.image.split("@", 1)[1]
        image = json.loads(self.command(["image", "inspect", image_id]))[0]
        if image["Id"] != image_id:
            raise RunnerFailure("image_identity_mismatch")
        allowed_env = {"PATH", "LANG", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256", "PYTHONDONTWRITEBYTECODE",
                       "PYTHONUNBUFFERED", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "TMPDIR", "HOME"}
        if image["Config"].get("Volumes") or any(e.split("=", 1)[0] not in allowed_env for e in image["Config"].get("Env", [])):
            raise RunnerFailure("image_has_volumes_or_unapproved_environment")
        if "name=seccomp,profile=builtin" not in info.get("SecurityOptions", []):
            raise RunnerFailure("default_seccomp_required")
        return image_id

    def run(self, files, paths, profile, active=lambda: True):
        image = self.preflight(profile)
        name = "reposhield-job-" + uuid.uuid4().hex
        cap = profile.output_bytes
        args = ["create", "--pull=never", "--no-healthcheck", "--name", name, "--label", "reposhield.restricted=true",
                "--label", "reposhield.deadline=" + str(int(time.time()) + profile.timeout_seconds), "-i",
                "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--user", f"{profile.uid}:{profile.uid}", "--pids-limit", str(profile.pids),
                "--memory", f"{profile.memory_mb}m", "--memory-swap", f"{profile.memory_mb}m",
                "--cpus", str(profile.cpu_millis / 1000), "--shm-size=64k", "--ulimit", "core=0",
                "--ulimit", "nofile=128:128", "--log-driver=none",
                "--tmpfs", f"/work:rw,noexec,nosuid,nodev,size={profile.disk_mb}m,uid={profile.uid},gid={profile.uid},mode=700",
                "--entrypoint", "python", image, "-I", "/opt/reposhield/entry.py"]
        data = json.dumps({"files": {p: base64.b64encode(b).decode() for p, b in files.items()},
                           "test_paths": paths, "output_bytes": max(1, cap // 8)}).encode()
        process = None
        stop_polling = threading.Event()
        try:
            self.command(args)
            # Snapshot the actual configuration for evidence, rather than echoing desired flags.
            inspection = json.loads(self.command(["inspect", name]))[0]
            if not active():
                raise RunnerFailure("session_inactive")
            if int(time.time()) >= int(inspection["Config"]["Labels"]["reposhield.deadline"]):
                raise RunnerFailure("timeout_before_start")
            process = subprocess.Popen([self.docker, "start", "-ai", name], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output, overflow = bytearray(), threading.Event()
            def write():
                try:
                    process.stdin.write(data)
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            def read():
                for chunk in iter(lambda: process.stdout.read(4096), b""):
                    if len(output) + len(chunk) > cap:
                        overflow.set()
                        return
                    output.extend(chunk)
            writer = threading.Thread(target=write, daemon=True)
            reader = threading.Thread(target=read, daemon=True)
            writer.start()
            reader.start()
            # A stalled control channel must not suspend the independent wall timer.
            authorization = {"active": True, "checked": time.monotonic()}
            def poll_authority():
                while not stop_polling.wait(0.2):
                    try: authorization["active"] = active()
                    except Exception: authorization["active"] = False
                    authorization["checked"] = time.monotonic()
                    if not authorization["active"]: return
            threading.Thread(target=poll_authority, daemon=True).start()
            deadline = time.monotonic() + profile.timeout_seconds
            while process.poll() is None:
                if overflow.is_set(): raise RunnerFailure("output_limit")
                if time.monotonic() >= deadline: raise RunnerFailure("timeout")
                if not authorization["active"] or time.monotonic() - authorization["checked"] > 2:
                    raise RunnerFailure("session_inactive")
                time.sleep(0.1)
            reader.join(timeout=2)
            if reader.is_alive() or overflow.is_set(): raise RunnerFailure("output_limit")
            if process.returncode: raise RunnerFailure("container_failed")
            try:
                observation = json.loads(output)
            except (ValueError, UnicodeError):
                raise RunnerFailure("invalid_runner_output") from None
            if not isinstance(observation, dict): raise RunnerFailure("invalid_runner_output")
            evidence = test_evidence(observation, paths)
            return {**evidence, "container_id": inspection["Id"], "image_id": inspection["Image"],
                    "isolation": inspection["HostConfig"],
                    "mode": "DEVELOPMENT EXECUTION" if self.development_desktop else "CONTROLLED SESSION"}
        finally:
            stop_polling.set()
            # rm -f also kills descendants in the container PID namespace.
            try:
                self.command(["rm", "-f", name])
            finally:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
