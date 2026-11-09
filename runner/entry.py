"""Trusted image entrypoint. Input/output are bounded observations, not attestations."""
import base64
import json
from pathlib import Path
import subprocess
import sys


def main():
    raw = sys.stdin.buffer.read(9 * 1024 * 1024 + 1)
    if len(raw) > 9 * 1024 * 1024:
        raise ValueError("input too large")
    task = json.loads(raw)
    root = Path("/work/source")
    root.mkdir()
    Path("/work/tmp").mkdir()
    for name, encoded in task["files"].items():
        if not name or any(p in ("", ".", "..") for p in name.split("/")) or "\\" in name:
            raise ValueError("invalid path")
        path = root / name
        if not path.is_relative_to(root):
            raise ValueError("invalid path")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(encoded, validate=True))
    report = Path("/work/results.xml")
    cap = task["output_bytes"]
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/work", "TMPDIR": "/work/tmp",
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    output = bytearray()
    def run(cmd, environment):
        child = subprocess.Popen(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, env=environment)
        for chunk in iter(lambda: child.stdout.read(4096), b""):
            if len(output) + len(chunk) > cap:
                child.kill()
                raise ValueError("command output limit")
            output.extend(chunk)
        return child.wait()
    requirements = root / "requirements.txt"
    if requirements.exists():
        install = [sys.executable, "-I", "-m", "pip", "install", "--no-index", "--no-deps", "--no-cache-dir",
                   "--disable-pip-version-check", "--only-binary=:all:", "--target=/work/deps",
                   "--find-links=/work/source/wheels", "-r", str(requirements)]
        if run(install, env):
            raise ValueError("dependency preparation failed")
    env["PYTHONPATH"] = "/work/deps:/work/source"
    cmd = [sys.executable, "-I", "/opt/reposhield/pytest_entry.py", "-c", "/opt/reposhield/pytest.ini", "-q", "-p", "no:cacheprovider",
           "--rootdir=/work/source", "--confcutdir=/work/source", "--junitxml=" + str(report), "--", *task["test_paths"]]
    code = run(cmd, env)
    if not report.is_file() or report.is_symlink():
        raise ValueError("missing test report")
    with report.open("rb") as f:
        xml = f.read(cap + 1)
    if len(xml) > cap:
        raise ValueError("test report limit")
    observations = Path("/work/observations.json")
    if observations.is_symlink(): raise ValueError("linked observations")
    with observations.open("rb") as f:
        observed = f.read(cap + 1)
    if len(observed) > cap: raise ValueError("observations limit")
    print(json.dumps({"exit_code": code, "stdout": output.decode("utf-8", "replace"),
                      "junit": xml.decode("utf-8", "strict"), "files": json.loads(observed)}, separators=(",", ":")))


if __name__ == "__main__":
    main()
