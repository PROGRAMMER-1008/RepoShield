from __future__ import annotations

import hashlib
import json
import os
import re

_GLOB_CACHE: dict[str, re.Pattern] = {}


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _translate(pat: str) -> str:
    i, out = 0, []
    while i < len(pat):
        c = pat[i]
        if c == "*":
            if pat[i:i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
            elif pat[i:i + 2] == "**":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = pat.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
                i += 1
            else:
                out.append(pat[i:j + 1])
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def glob_match(pattern: str, path: str) -> bool:
    """gitignore-flavoured glob: `**` crosses directories, `*` does not,
    and a pattern with no slash matches the basename at any depth."""
    if path.startswith("./"):
        path = path[2:]
    rx = _GLOB_CACHE.get(pattern)
    if rx is None:
        pat = pattern
        if pat.startswith("/"):
            pat = pat[1:]
        elif "/" not in pat:
            pat = "**/" + pat
        rx = re.compile("^" + _translate(pat) + "$")
        _GLOB_CACHE[pattern] = rx
    return bool(rx.match(path))


def match_any(patterns, path: str) -> bool:
    return any(glob_match(p, path) for p in patterns)


def atomic_write(path: str, text: str) -> None:
    """Write-then-rename so concurrent readers (parallel runs / workers) never see a half-written file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
