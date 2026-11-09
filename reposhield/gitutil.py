from __future__ import annotations

import hashlib
import inspect
import io
import os
import re
import subprocess
import tarfile
from dataclasses import dataclass


class GitError(RuntimeError):
    pass


def _run(repo: str, *args: str, input: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", "-c", "core.quotepath=off", "-C", repo, *args],
                       input=input, capture_output=True)
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p


def git(repo: str, *args: str, check: bool = True) -> str:
    return _run(repo, *args, check=check).stdout.decode("utf-8", "replace")


def is_git_repo(repo: str) -> bool:
    return _run(repo, "rev-parse", "--git-dir", check=False).returncode == 0


def git_dir(repo: str) -> str:
    return git(repo, "rev-parse", "--absolute-git-dir").strip()


def resolve(repo: str, ref: str) -> str:
    if not ref or ref.startswith("-") or any(ch.isspace() for ch in ref):
        raise GitError(f"invalid git ref: {ref!r}")          # also blocks option injection (--output=...)
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def merge_base(repo: str, a: str, b: str) -> str:
    return git(repo, "merge-base", a, b).strip()


def detect_base(repo: str) -> str:
    for ref in ("origin/main", "origin/master", "main", "master"):
        if _run(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0:
            return ref
    raise GitError("could not detect a base branch; pass --base")


@dataclass(frozen=True)
class Change:
    status: str   # A | M | D | T
    path: str


def diff_changes(repo: str, base: str, head: str) -> list[Change]:
    out = git(repo, "diff", "--no-ext-diff", "--no-textconv", "--name-status", "--no-renames", "-z", base, head)
    toks = [t for t in out.split("\0") if t != ""]
    return [Change(toks[i][0], toks[i + 1]) for i in range(0, len(toks) - 1, 2)]


def diff_numstat(repo: str, base: str, head: str) -> dict[str, tuple[int, int]]:
    out = git(repo, "diff", "--no-ext-diff", "--no-textconv", "--numstat", "--no-renames", "-z", base, head)
    res: dict[str, tuple[int, int]] = {}
    for rec in [r for r in out.split("\0") if r]:
        a, d, p = rec.split("\t", 2)
        res[p] = (0, 0) if a == "-" else (int(a), int(d))
    return res


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


_ESC = {"n": 10, "t": 9, "r": 13, '"': 34, "\\": 92, "a": 7, "b": 8, "f": 12, "v": 11}


def unquote_c(s: str) -> str:
    """Undo git's C-style path quoting (used for names containing quotes, backslashes, control characters)."""
    b, out, i = s[1:-1], bytearray(), 0
    while i < len(b):
        c = b[i]
        if c == "\\" and i + 1 < len(b):
            n = b[i + 1]
            if n in "01234567":
                out.append(int(b[i + 1:i + 4], 8) & 0xFF)
                i += 4
                continue
            if n in _ESC:
                out.append(_ESC[n])
                i += 2
                continue
        out += c.encode("utf-8")
        i += 1
    return out.decode("utf-8", "replace")


def _header_path(line: str) -> str | None:
    """Parse a `+++ b/<path>` header. git appends a TAB after names that contain spaces."""
    rest = line[4:].rstrip("\t")
    if rest == "/dev/null":
        return None
    if rest.startswith('"') and rest.endswith('"') and len(rest) > 1:
        rest = unquote_c(rest)
    return rest[2:] if rest[:2] in ("b/", "a/") else rest


def diff_added_lines(repo: str, base: str, head: str) -> dict[str, list[tuple[int, str]]]:
    out = git(repo, "diff", "--no-ext-diff", "--no-textconv", "-U0", "--no-renames", "--no-color", base, head)
    res: dict[str, list[tuple[int, str]]] = {}
    cur, lineno = None, 0
    for line in out.splitlines():
        if line.startswith("+++ "):
            cur = _header_path(line)
            if cur is not None:
                res.setdefault(cur, [])
        elif line.startswith("@@"):
            m = _HUNK.match(line)
            lineno = int(m.group(1)) if m else 0
        elif cur is not None and line.startswith("+") and not line.startswith("+++"):
            res[cur].append((lineno, line[1:]))
            lineno += 1
    return res


class GitTree:
    """Read-only view of a commit's files (no checkout needed)."""

    def __init__(self, repo: str, sha: str):
        self.repo, self.sha = repo, sha
        self._files: dict[str, str] | None = None

    def files(self) -> dict[str, str]:
        if self._files is None:
            out = git(self.repo, "ls-tree", "-r", "-z", self.sha)
            files = {}
            for rec in [r for r in out.split("\0") if r]:
                meta, path = rec.split("\t", 1)
                mode, typ, oid = meta.split()
                if typ == "blob" and mode != "120000":      # skip symlinks
                    files[path] = oid
            self._files = files
        return self._files

    def read(self, path: str) -> bytes | None:
        p = _run(self.repo, "show", f"{self.sha}:{path}", check=False)
        return p.stdout if p.returncode == 0 else None

    def read_many(self, paths: list[str]) -> dict[str, bytes]:
        if not paths:
            return {}
        inp = "".join(f"{self.sha}:{p}\n" for p in paths).encode()
        out = _run(self.repo, "cat-file", "--batch", input=inp).stdout
        res, pos = {}, 0
        for p in paths:
            nl = out.index(b"\n", pos)
            header = out[pos:nl].split()
            pos = nl + 1
            if len(header) == 3 and header[1] == b"blob":
                size = int(header[2])
                res[p] = out[pos:pos + size]
                pos += size + 1
        return res


class DirTree:
    """Same interface over a plain directory (benchmarks, tests, exported workspaces)."""

    def __init__(self, root: str):
        self.root = root

    def files(self) -> dict[str, str]:
        res = {}
        for dp, dn, fn in os.walk(self.root):
            dn[:] = [d for d in dn if d not in (".git", "__pycache__", ".reposhield", ".pytest_cache")]
            for f in fn:
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, self.root).replace(os.sep, "/")
                with open(full, "rb") as fh:
                    res[rel] = hashlib.sha1(fh.read()).hexdigest()
        return res

    def read(self, path: str) -> bytes | None:
        try:
            with open(os.path.join(self.root, path), "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def read_many(self, paths):
        return {p: d for p in paths if (d := self.read(p)) is not None}


def _safe_members(tf: tarfile.TarFile, dest: str):
    """Version-independent extraction guard (works on every Python 3.10.x, unlike tarfile's `filter=`).
    Only regular files and directories whose resolved path stays inside `dest`; links/devices are skipped."""
    root = os.path.realpath(dest)
    for m in tf.getmembers():
        if not (m.isfile() or m.isdir()):
            continue
        target = os.path.realpath(os.path.join(root, m.name))
        if target != root and not target.startswith(root + os.sep):
            continue
        m.mode = 0o755 if m.isdir() else 0o644
        yield m


def export_tree(repo: str, sha: str, dest: str) -> None:
    data = _run(repo, "archive", "--format=tar", sha).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        kw = {"filter": "data"} if "filter" in inspect.signature(tf.extractall).parameters else {}
        tf.extractall(dest, members=list(_safe_members(tf, dest)), **kw)
