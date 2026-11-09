"""Conservative selective test execution.

Principle: when unsure, run MORE tests. Every selected test carries the evidence for why it was chosen.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .gitutil import Change
from .graph import Graph
from .util import match_any

CONFIG_FILES = ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "setup.py", "requirements", "Pipfile", "poetry.lock")


@dataclass
class SelectedTest:
    path: str
    confidence: str            # HIGH | MEDIUM | LOW
    reasons: list = field(default_factory=list)


@dataclass
class TestPlan:
    mode: str                  # IMPACTED | FULL | NONE
    strategy: str
    tests: list                # list[SelectedTest]
    total_tests: int
    fallback_reasons: list
    ignored: list
    full: bool = False

    @property
    def reduction_pct(self) -> float:
        if not self.total_tests:
            return 0.0
        return round(100.0 * (1 - len(self.tests) / self.total_tests), 1)

    def to_dict(self) -> dict:
        return {"mode": self.mode, "strategy": self.strategy, "selected": len(self.tests), "total": self.total_tests,
                "reduction_pct": self.reduction_pct, "fallback_reasons": self.fallback_reasons, "ignored": self.ignored,
                "tests": [{"path": t.path, "confidence": t.confidence, "reasons": t.reasons} for t in self.tests]}


def _label(conf: float) -> str:
    return "HIGH" if conf >= 0.95 else "MEDIUM" if conf >= 0.7 else "LOW"


def _is_config(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return any(base.startswith(c) for c in CONFIG_FILES)


def select_tests(head: Graph, base: Graph | None, changes: list[Change], *, strategy: str = "safe",
                 coverage: dict | None = None, ignore_paths=(), force_full=(), required_files=()) -> TestPlan:
    all_tests = head.tests()
    sel: dict[str, SelectedTest] = {}
    fallback, ignored = list(force_full), []
    effective = strategy
    if strategy == "balanced" and not coverage:
        effective = "safe"
        fallback_note = True
    else:
        fallback_note = False

    def add(test, conf, reason):
        st = sel.setdefault(test, SelectedTest(test, conf, []))
        order = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
        if order[conf] > order[st.confidence]:
            st.confidence = conf
        if len(st.reasons) < 6:
            st.reasons.append(reason)

    for ch in changes:
        p = ch.path
        if match_any(ignore_paths, p):
            ignored.append(p)
            continue
        if _is_config(p):
            fallback.append(f"{p}: test/dependency configuration changed")
            continue
        if p.rsplit("/", 1)[-1] == "conftest.py":
            d = p.rsplit("/", 1)[0] if "/" in p else ""
            if not d:
                fallback.append(f"{p}: root conftest.py affects every test")
            else:
                for t in all_tests:
                    if t.startswith(d + "/"):
                        add(t, "MEDIUM", {"changed": p, "kind": "conftest"})
            continue
        if not p.endswith(".py"):
            fallback.append(f"{p}: unmapped file type (cannot prove it does not affect tests)")
            continue
        if ch.status == "D":
            if base is None:
                fallback.append(f"{p}: deleted and no base graph available")
                continue
            imp = base.impact([p])
            hit = False
            for q, i in imp.items():
                if q != p and q in head.files and head.files[q].is_test:
                    add(q, _label(i.conf), {"changed": p, "kind": "deleted-dependency", "path": i.via})
                    hit = True
            if not hit and not (p in base.files and base.files[p].is_test):
                fallback.append(f"{p}: deleted module with no dependent tests found")
            continue
        if p in head.files and head.files[p].is_test:
            add(p, "HIGH", {"changed": p, "kind": "test-changed"})
            continue
        if p not in head.files:
            fallback.append(f"{p}: not present in head graph")
            continue

        imp = head.impact([p])
        static = {q: i for q, i in imp.items() if q != p and head.files[q].is_test}
        cov_tests = set((coverage or {}).get(p, [])) if effective == "balanced" else set()
        if effective == "balanced" and cov_tests:
            direct = {q for q, i in static.items() if i.distance == 1}
            for q in sorted(cov_tests & set(all_tests)):
                add(q, "HIGH", {"changed": p, "kind": "coverage"})
            for q in sorted(direct):
                add(q, "HIGH", {"changed": p, "kind": "direct-import", "path": static[q].via})
        else:
            for q, i in sorted(static.items()):
                add(q, _label(i.conf), {"changed": p, "kind": "static-dependency", "path": i.via, "distance": i.distance})
        if not static and not cov_tests:
            fallback.append(f"{p}: no test reaches this file (no mapping => run everything)")

    for rf in required_files:
        add(rf, "HIGH", {"kind": "required-by-policy"})

    if fallback:
        tests = [SelectedTest(t, "LOW", [{"kind": "full-suite-fallback"}]) for t in all_tests]
        plan = TestPlan("FULL", effective, tests, len(all_tests), fallback, ignored, full=True)
    elif not sel:
        plan = TestPlan("NONE", effective, [], len(all_tests), [], ignored)
    else:
        plan = TestPlan("IMPACTED", effective, [sel[k] for k in sorted(sel)], len(all_tests), [], ignored)
    if fallback_note:
        plan.strategy = "safe (balanced unavailable: no coverage baseline)"
    return plan
