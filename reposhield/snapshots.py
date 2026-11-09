"""Bounded, content-addressed snapshots. No extraction of archive paths or links."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re

from .action_policy import safe_path, patch_paths

MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_FILES = 1000


def encode_snapshot(files):
    if not files or len(files) > MAX_FILES or any(not safe_path(p) for p in files):
        raise ValueError("invalid snapshot paths/count")
    if any(any(q.startswith(p + "/") for q in files) for p in files):
        raise ValueError("snapshot file/directory collision")
    data = json.dumps({"version": 1, "files": {p: base64.b64encode(b).decode() for p, b in files.items()}},
                      sort_keys=True, separators=(",", ":")).encode()
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot too large")
    return data


def decode_snapshot(data):
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot too large")
    obj = json.loads(data)
    if set(obj) != {"version", "files"} or obj["version"] != 1:
        raise ValueError("unsupported snapshot")
    files = {p: base64.b64decode(v, validate=True) for p, v in obj["files"].items()}
    if encode_snapshot(files) != data:
        raise ValueError("snapshot must have canonical encoding")
    return files


class SnapshotStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, files):
        data = encode_snapshot(files)
        revision = "sha256:" + hashlib.sha256(data).hexdigest()
        path = self.root / (revision[7:] + ".json")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if self.get(revision) != files:
                raise ValueError("snapshot collision")
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        return revision

    def get(self, revision):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", revision):
            raise ValueError("invalid snapshot identity")
        path = self.root / (revision[7:] + ".json")
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ValueError("snapshot link rejected")
        with path.open("rb") as f:
            data = f.read(MAX_SNAPSHOT_BYTES + 1)
        if "sha256:" + hashlib.sha256(data).hexdigest() != revision:
            raise ValueError("snapshot integrity mismatch")
        return decode_snapshot(data)


def apply_patch(files, patch):
    """Apply the policy's narrow patch format to bytes; never invoke repository code."""
    paths = patch_paths(patch)
    result = dict(files)
    lines, i = patch.splitlines(keepends=True), 0
    for path in paths:
        if path not in files:
            raise ValueError("patch target missing")
        old = files[path].decode("utf-8").splitlines(keepends=True)
        i += 2
        output, cursor = [], 0
        while i < len(lines) and lines[i].startswith("@@"):
            match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@\n?", lines[i])
            if not match:
                raise ValueError("invalid patch hunk")
            old_start, old_count = int(match[1]), int(match[2] or 1)
            new_start, new_count = int(match[3]), int(match[4] or 1)
            start = old_start - 1 if old_count else old_start
            if start < cursor or start > len(old):
                raise ValueError("overlapping/out-of-range patch")
            output.extend(old[cursor:start])
            cursor = start
            if (new_start - 1 if new_count else new_start) != len(output):
                raise ValueError("new hunk position mismatch")
            i += 1
            while old_count or new_count:
                line = lines[i]
                kind, text = line[0], line[1:]
                if kind in " -":
                    if cursor >= len(old) or old[cursor] != text:
                        raise ValueError("patch context mismatch")
                    cursor += 1
                    old_count -= 1
                if kind in " +":
                    output.append(text)
                    new_count -= 1
                i += 1
        output.extend(old[cursor:])
        result[path] = "".join(output).encode()
    encode_snapshot(result)  # enforce output size and shape before storing
    return result
