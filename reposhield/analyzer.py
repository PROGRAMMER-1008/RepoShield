"""Python static analysis: imports, definitions, tests, dynamic-import detection."""
from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass, field, asdict

from . import ANALYZER_VERSION


MAX_PARSE_BYTES = 2 * 1024 * 1024


def is_test_path(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return path.endswith(".py") and (base.startswith("test_") or base.endswith("_test.py"))


@dataclass
class ImportRef:
    module: str
    names: list
    level: int
    line: int
    kind: str          # import | from | dynamic_const


@dataclass
class Def:
    name: str
    kind: str          # function | class | method
    line: int
    end: int


@dataclass
class TestInfo:
    name: str
    line: int
    asserts: int
    skipped: bool


@dataclass
class ParsedFile:
    path: str
    cid: str
    ok: bool = True
    error: str = ""
    loc: int = 0
    imports: list = field(default_factory=list)
    defs: list = field(default_factory=list)
    tests: list = field(default_factory=list)
    dynamic: list = field(default_factory=list)      # [[line, description]] unresolved dynamic imports

    @property
    def is_test(self) -> bool:
        return is_test_path(self.path)

    def payload(self) -> dict:
        d = asdict(self)
        d.pop("path")
        return d

    @classmethod
    def from_payload(cls, path: str, d: dict) -> "ParsedFile":
        return cls(path=path, cid=d["cid"], ok=d["ok"], error=d["error"], loc=d["loc"],
                   imports=[ImportRef(**i) for i in d["imports"]],
                   defs=[Def(**i) for i in d["defs"]],
                   tests=[TestInfo(**i) for i in d["tests"]],
                   dynamic=d["dynamic"])


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        return _dotted(node.func)
    return ".".join(reversed(parts))


def _is_skip_marker(dec) -> bool:
    name = _dotted(dec)
    return name.endswith(("mark.skip", "mark.skipif", "mark.xfail", "unittest.skip", "unittest.skipIf",
                          "unittest.skipUnless", "unittest.expectedFailure")) or name in ("skip", "skipif", "xfail")


def _test_stats(fn, inherited_skip: bool) -> TestInfo:
    asserts, skipped = 0, inherited_skip or any(_is_skip_marker(d) for d in fn.decorator_list)
    for n in ast.walk(fn):
        if isinstance(n, ast.Assert):
            asserts += 1
        elif isinstance(n, ast.Call):
            name = _dotted(n.func)
            last = name.rsplit(".", 1)[-1]
            if last.startswith("assert"):
                asserts += 1
            elif name in ("pytest.skip", "pytest.xfail", "self.skipTest", "unittest.skip"):
                skipped = True
            elif name == "pytest.raises" or name == "pytest.warns":
                asserts += 1
    return TestInfo(fn.name, fn.lineno, asserts, skipped)


def parse_source(path: str, data: bytes, cid: str) -> ParsedFile:
    pf = ParsedFile(path=path, cid=cid)
    if len(data) > MAX_PARSE_BYTES:
        pf.ok, pf.error = False, f"skipped: file larger than {MAX_PARSE_BYTES // 1024 // 1024} MB (not analysed)"
        return pf
    try:
        text = data.decode("utf-8")
        pf.loc = text.count("\n") + 1
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError, UnicodeDecodeError, RecursionError, MemoryError) as e:
        pf.ok, pf.error = False, f"{type(e).__name__}: {e}"
        return pf

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                pf.imports.append(ImportRef(a.name, [], 0, node.lineno, "import"))
        elif isinstance(node, ast.ImportFrom):
            pf.imports.append(ImportRef(node.module or "", [a.name for a in node.names],
                                        node.level or 0, node.lineno, "from"))
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name in ("__import__", "importlib.import_module", "import_module"):
                arg = node.args[0] if node.args else None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    pf.imports.append(ImportRef(arg.value, [], 0, node.lineno, "dynamic_const"))
                else:
                    pf.dynamic.append([node.lineno, f"{name}(<non-constant>)"])

    def visit(body, prefix, in_class):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = prefix + n.name
                pf.defs.append(Def(q, "method" if in_class else "function", n.lineno, getattr(n, "end_lineno", n.lineno)))
                visit(n.body, q + ".", False)
            elif isinstance(n, ast.ClassDef):
                q = prefix + n.name
                pf.defs.append(Def(q, "class", n.lineno, getattr(n, "end_lineno", n.lineno)))
                visit(n.body, q + ".", True)

    visit(tree.body, "", False)

    if is_test_path(path):
        module_skip = any(
            isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
            and any(_is_skip_marker(c) for c in ast.walk(n.value) if isinstance(c, (ast.Attribute, ast.Call, ast.Name)))
            for n in tree.body)
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
                pf.tests.append(_test_stats(n, module_skip))
            elif isinstance(n, ast.ClassDef) and n.name.startswith("Test"):
                cls_skip = module_skip or any(_is_skip_marker(d) for d in n.decorator_list)
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith("test"):
                        ti = _test_stats(m, cls_skip)
                        ti.name = f"{n.name}::{m.name}"
                        pf.tests.append(ti)
    return pf


class ParseCache:
    """Content-addressed parse cache: same blob => no re-parse. This is what makes graph updates incremental."""

    def __init__(self, path: str | None = None):
        self.path, self.data, self.hits, self.misses = path, {}, 0, 0
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    blob = json.load(fh)
                if blob.get("v") == ANALYZER_VERSION:
                    self.data = blob["entries"]
            except (OSError, ValueError, KeyError):
                self.data = {}

    def get(self, path: str, cid: str, reader) -> ParsedFile:
        key = f"{cid}:{int(is_test_path(path))}"
        hit = self.data.get(key)
        if hit is not None:
            self.hits += 1
            return ParsedFile.from_payload(path, hit)
        self.misses += 1
        raw = reader(path)
        pf = parse_source(path, raw if raw is not None else b"", cid)
        self.data[key] = pf.payload()
        return pf

    def save(self):
        if self.path:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"v": ANALYZER_VERSION, "entries": self.data}, fh)
            os.replace(tmp, self.path)
