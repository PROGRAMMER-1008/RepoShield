"""File-level dependency graph with incremental update and reverse-reachability impact analysis."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .analyzer import ParsedFile, ParseCache, ImportRef


@dataclass
class Edge:
    src: str
    dst: str
    kind: str       # import | implicit (ancestor package __init__) | dynamic
    conf: float
    line: int


@dataclass
class Impact:
    distance: int
    via: list        # path of files from a changed file to this one
    conf: float      # weakest edge confidence along `via`


def module_names(path: str, roots) -> list[str]:
    names = []
    for r in roots:
        if r in ("", "."):
            rel = path
        elif path.startswith(r.rstrip("/") + "/"):
            rel = path[len(r.rstrip("/")) + 1:]
        else:
            continue
        if not rel.endswith(".py"):
            continue
        rel = rel[:-3]
        parts = rel.split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            names.append(".".join(parts))
    return names


class Graph:
    def __init__(self, roots=("", "src")):
        self.roots = tuple(roots)
        self.files: dict[str, ParsedFile] = {}
        self.out: dict[str, list[Edge]] = {}
        self.inc: dict[str, list[Edge]] = {}
        self.index: dict[str, str] = {}
        self.primary: dict[str, str] = {}
        self.last_update = {"parsed": 0, "reused": 0}

    # ---------- construction ----------
    @classmethod
    def build(cls, tree, cache: ParseCache | None = None, roots=("", "src")) -> "Graph":
        g = cls(roots)
        cache = cache or ParseCache()
        before = cache.misses
        for path, cid in tree.files().items():
            if path.endswith(".py"):
                g.files[path] = cache.get(path, cid, tree.read)
        g.last_update = {"parsed": cache.misses - before, "reused": len(g.files) - (cache.misses - before)}
        g._rebuild()
        return g

    def clone(self) -> "Graph":
        g = Graph(self.roots)
        g.files = dict(self.files)
        g._rebuild()
        return g

    def update(self, tree, changed: set[str], removed: set[str], cache: ParseCache | None = None) -> dict:
        """Incremental update: re-parse only changed files (content-addressed), drop removed, re-resolve edges."""
        cache = cache or ParseCache()
        before = cache.misses
        tree_files = tree.files()
        for p in removed:
            self.files.pop(p, None)
        for p in changed:
            if p.endswith(".py") and p in tree_files:
                self.files[p] = cache.get(p, tree_files[p], tree.read)
        self._rebuild()
        parsed = cache.misses - before
        self.last_update = {"parsed": parsed, "reused": len(self.files) - parsed}
        return self.last_update

    # ---------- edge resolution ----------
    def _rebuild(self):
        self.index, self.primary = {}, {}
        for p in self.files:
            names = module_names(p, self.roots)
            for n in names:
                self.index.setdefault(n, p)
            if names:
                self.primary[p] = min(names, key=lambda s: s.count(".") if p.endswith("__init__.py") else len(s))
        self.out = {p: [] for p in self.files}
        self.inc = {p: [] for p in self.files}
        for p, pf in self.files.items():
            seen: dict[tuple, Edge] = {}
            for ref in pf.imports:
                for e in self._resolve(p, ref):
                    k = (e.dst, e.kind)
                    if k not in seen or e.line < seen[k].line:
                        seen[k] = e
            for e in seen.values():
                self.out[p].append(e)
                self.inc[e.dst].append(e)

    def _package_parts(self, path: str) -> list[str]:
        name = self.primary.get(path)
        if name is None:
            return []
        parts = name.split(".")
        return parts if path.endswith("/__init__.py") or path == "__init__.py" else parts[:-1]

    def _resolve(self, src: str, ref: ImportRef) -> list[Edge]:
        base = ref.module
        if ref.level > 0:
            pkg = self._package_parts(src)
            up = ref.level - 1
            if up > len(pkg):
                return []
            pkg = pkg[:len(pkg) - up]
            base = ".".join(pkg + ([ref.module] if ref.module else []))
        kind = "dynamic" if ref.kind == "dynamic_const" else "import"
        conf = 0.9 if kind == "dynamic" else 1.0
        edges: list[Edge] = []

        def add(dst, k, c):
            if dst and dst != src:
                edges.append(Edge(src, dst, k, c, ref.line))

        target = self.index.get(base) if base else None
        add(target, kind, conf)
        if ref.kind == "from":
            for n in ref.names:
                if n == "*":
                    continue
                sub = self.index.get(f"{base}.{n}" if base else n)
                add(sub, kind, conf)
        if base:
            parts = base.split(".")
            for i in range(1, len(parts) + (0 if target else 1)):
                anc = self.index.get(".".join(parts[:i]))
                if anc and anc != target:
                    add(anc, "implicit", 1.0)
        return edges

    # ---------- queries ----------
    def tests(self) -> list[str]:
        return sorted(p for p, f in self.files.items() if f.is_test)

    def edge_count(self) -> int:
        return sum(len(v) for v in self.out.values())

    def impact(self, seeds, min_conf: float = 0.0) -> dict[str, Impact]:
        """Reverse reachability from `seeds`: files that *potentially* depend on a changed file."""
        res: dict[str, Impact] = {}
        q = deque()
        for s in seeds:
            if s in self.files:
                res[s] = Impact(0, [s], 1.0)
                q.append(s)
        while q:
            cur = q.popleft()
            for e in self.inc.get(cur, []):
                if e.src in res or e.conf < min_conf:
                    continue
                prev = res[cur]
                res[e.src] = Impact(prev.distance + 1, prev.via + [e.src], min(prev.conf, e.conf))
                q.append(e.src)
        return res

    def reachable(self, start: str, stop_at=None, kinds=None) -> dict[str, list[str]]:
        """Forward BFS from `start`; returns {file: path}. Does not expand through files where stop_at(file) is True."""
        paths = {start: [start]}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur != start and stop_at and stop_at(cur):
                continue
            for e in self.out.get(cur, []):
                if kinds and e.kind not in kinds:
                    continue
                if e.dst not in paths:
                    paths[e.dst] = paths[cur] + [e.dst]
                    q.append(e.dst)
        return paths

    def edge_between(self, src: str, dst: str) -> Edge | None:
        for e in self.out.get(src, []):
            if e.dst == dst:
                return e
        return None

    def edge_set(self) -> set:
        return {(e.src, e.dst, e.kind, e.conf) for es in self.out.values() for e in es}

    # ---------- (de)serialisation ----------
    def to_dict(self) -> dict:
        return {"roots": list(self.roots), "files": {p: f.payload() for p, f in self.files.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "Graph":
        g = cls(d["roots"])
        g.files = {p: ParsedFile.from_payload(p, pl) for p, pl in d["files"].items()}
        g._rebuild()
        return g
