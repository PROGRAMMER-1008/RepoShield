"""Policy-as-code: parse/validate `.reposhield.yml` and evaluate rules deterministically."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import yaml

from .gitutil import Change
from .graph import Graph
from .models import Finding
from .util import canonical_json, sha256_hex, glob_match, match_any

POLICY_FILE = ".reposhield.yml"
SEVERITIES = ("critical", "high", "medium", "low")
RULE_TYPES = {"forbidden_path", "forbidden_import", "required_test", "require_review",
              "max_changed_lines", "test_mode", "forbidden_command"}

DEFAULTS = {
    "version": 1,
    "project": {"name": "unnamed"},
    "verification": {
        "test_mode": "impacted",           # impacted | full
        "strategy": "safe",                # safe (static transitive) | balanced (coverage-pruned)
        "test_command": ["python", "-m", "pytest"],
        "timeout_seconds": 120,
        "test_integrity": "review",        # review | block | off
        "ignore_paths": ["**/*.md", "**/*.rst", "docs/**", "LICENSE*", ".gitignore", ".github/**", POLICY_FILE],
    },
    "sandbox": {"backend": "auto", "memory_mb": 2048, "cpus": 2, "pids": 256, "max_output_mb": 5,
                "network": False, "image": "reposhield-runner:py312", "require_isolation": False},
    "policies": [],
    "actions": {"allow": [], "deny": [], "max_ttl_seconds": 60},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def validate(cfg: dict) -> list[str]:
    errs = []
    if not isinstance(cfg, dict):
        return ["policy file must be a YAML mapping"]
    if cfg.get("version") != 1:
        errs.append("version must be 1")
    seen = set()
    for i, p in enumerate(cfg.get("policies") or []):
        pid = p.get("id") if isinstance(p, dict) else None
        if not pid:
            errs.append(f"policies[{i}]: missing id")
            continue
        if pid in seen:
            errs.append(f"policy '{pid}': duplicate id")
        seen.add(pid)
        if p.get("severity", "high") not in SEVERITIES:
            errs.append(f"policy '{pid}': severity must be one of {SEVERITIES}")
        if p.get("on_fail") not in (None, "block", "review", "info"):
            errs.append(f"policy '{pid}': on_fail must be block|review|info")
        when = p.get("when") or {}
        if "changed" in when and not isinstance(when["changed"], list):
            errs.append(f"policy '{pid}': when.changed must be a list of globs")
        if not p.get("rules"):
            errs.append(f"policy '{pid}': needs at least one rule")
        for j, r in enumerate(p.get("rules") or []):
            t = r.get("type") if isinstance(r, dict) else None
            if t not in RULE_TYPES:
                errs.append(f"policy '{pid}' rule[{j}]: unknown type '{t}' (known: {sorted(RULE_TYPES)})")
                continue
            need = {"forbidden_path": ["paths"], "forbidden_import": ["from"], "required_test": ["paths"],
                    "max_changed_lines": ["max"], "test_mode": ["mode"], "forbidden_command": ["patterns"],
                    "require_review": []}[t]
            for k in need:
                if k not in r:
                    errs.append(f"policy '{pid}' rule[{j}] ({t}): missing '{k}'")
            if t == "forbidden_import" and not (r.get("to") or r.get("modules")):
                errs.append(f"policy '{pid}' rule[{j}] (forbidden_import): needs 'to' (repo paths) and/or 'modules' (package names)")
            if t == "test_mode" and r.get("mode") not in ("full", "impacted"):
                errs.append(f"policy '{pid}' rule[{j}]: mode must be full|impacted")
    return errs


def load_config(text: str) -> tuple[dict, list[str]]:
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        return copy.deepcopy(DEFAULTS), [f"YAML parse error: {e}"]
    errs = validate(raw)
    return _merge(DEFAULTS, raw if isinstance(raw, dict) else {}), errs


def policy_hash(cfg: dict) -> str:
    return sha256_hex(canonical_json(cfg))


STARTER = """\
version: 1
project:
  name: my-project

verification:
  test_mode: impacted        # impacted | full
  strategy: safe             # safe = static transitive impact, balanced = coverage-pruned
  test_integrity: review     # flag deleted/weakened/skipped tests (review | block | off)

policies:
  - id: no-ci-or-secret-edits
    severity: critical
    description: Autonomous changes must never touch CI workflows or credentials.
    rules:
      - type: forbidden_path
        paths: [".github/workflows/**", "*.pem", ".env"]

  - id: production-config
    severity: high
    description: Production configuration needs a human.
    when: {changed: ["config/production/**"]}
    rules:
      - type: require_review

  # Architectural boundary example (edit the globs for your repo):
  # - id: payments-isolation
  #   severity: critical
  #   description: Payment code cannot depend on analytics code.
  #   when: {changed: ["payments/**"]}
  #   rules:
  #     - type: forbidden_import
  #       from: "payments/**"
  #       to: "analytics/**"
  #       transitive: true

actions:                      # used by `reposhield action ...` (agent action gateway)
  allow: ["python -m pytest *", "pytest *"]
  deny: ["rm *", "curl *", "wget *", "git push*", "pip install*"]
  max_ttl_seconds: 60
"""


@dataclass
class RequiredTest:
    policy_id: str
    severity: str
    on_fail: str | None
    globs: list
    files: list


@dataclass
class EvalContext:
    changes: list[Change]
    head: Graph
    base: Graph | None
    numstat: dict
    added: dict


@dataclass
class PolicyOutcome:
    findings: list = field(default_factory=list)
    force_full: list = field(default_factory=list)       # reasons
    required: list = field(default_factory=list)         # RequiredTest


def _violations(graph: Graph, frm: str, to: str, transitive: bool) -> dict:
    srcs = [p for p in graph.files if glob_match(frm, p)]
    dsts = {p for p in graph.files if glob_match(to, p)}
    res = {}
    for s in srcs:
        if not transitive:
            for e in graph.out.get(s, []):
                if e.kind in ("import", "dynamic") and e.dst in dsts and e.dst != s:
                    res[(s, e.dst)] = {"line": e.line, "path": [s, e.dst]}
        else:
            reach = graph.reachable(s, stop_at=lambda f: glob_match(frm, f))
            for n, npath in reach.items():
                if n != s and glob_match(frm, n):
                    continue                      # that file is reported as its own source
                for e in graph.out.get(n, []):
                    if e.kind == "implicit" or e.dst not in dsts or e.dst == s or glob_match(frm, e.dst):
                        continue
                    cand = npath + [e.dst]
                    cur = res.get((s, e.dst))
                    if cur is None or len(cand) < len(cur["path"]):
                        first = graph.edge_between(s, cand[1])
                        res[(s, e.dst)] = {"line": first.line if first else e.line, "path": cand}
    return res


def _module_hit(name: str, patterns) -> str | None:
    for pat in patterns:
        if pat.endswith(".*"):
            pat = pat[:-2]
        if name == pat or name.startswith(pat + "."):
            return pat
    return None


def _module_violations(graph: Graph, frm: str, patterns) -> dict:
    """Imports of named modules (third-party or stdlib) inside files matching `frm`."""
    res = {}
    for path, pf in graph.files.items():
        if not glob_match(frm, path):
            continue
        for ref in pf.imports:
            if ref.level > 0:
                continue                                  # relative => in-repo, covered by 'to'
            cands = [ref.module] + ([f"{ref.module}.{n}" for n in ref.names if n != "*"] if ref.kind == "from" else [])
            for c in cands:
                hit = c and _module_hit(c, patterns)
                if hit:
                    res.setdefault((path, hit), {"line": ref.line, "module": c})
    return res


def evaluate_policies(cfg: dict, ctx: EvalContext) -> PolicyOutcome:
    out = PolicyOutcome()
    paths = [c.path for c in ctx.changes]
    for pol in cfg.get("policies") or []:
        pid, sev, on_fail = pol["id"], pol.get("severity", "high"), pol.get("on_fail")
        when = (pol.get("when") or {}).get("changed")
        matched = [p for p in paths if match_any(when, p)] if when else paths
        if when and not matched:
            out.findings.append(Finding("policy", pid, "policy", "NOT_APPLICABLE", sev, "no matching changed files"))
            continue
        for rule in pol["rules"]:
            t = rule["type"]
            F = lambda result, msg, ev=None: out.findings.append(
                Finding("policy", pid, t, result, sev, msg, ev or [], on_fail))
            desc = pol.get("description", "")

            if t == "forbidden_path":
                hits = [p for p in paths if match_any(rule["paths"], p)]
                if hits:
                    F("FAIL", f"{desc or 'forbidden path touched'}: {', '.join(hits[:5])}",
                      [{"file": p} for p in hits])
                else:
                    F("PASS", "no forbidden paths touched")

            elif t == "forbidden_import":
                trans = bool(rule.get("transitive", False))
                ev, pre = [], 0
                if rule.get("to"):
                    head_v = _violations(ctx.head, rule["from"], rule["to"], trans)
                    base_v = _violations(ctx.base, rule["from"], rule["to"], trans) if ctx.base else {}
                    new = {k: v for k, v in head_v.items() if k not in base_v}
                    pre += len(head_v) - len(new)
                    ev += [{"file": s_, "line": v["line"], "target": d, "path": v["path"]} for (s_, d), v in sorted(new.items())]
                if rule.get("modules"):
                    head_m = _module_violations(ctx.head, rule["from"], rule["modules"])
                    base_m = _module_violations(ctx.base, rule["from"], rule["modules"]) if ctx.base else {}
                    newm = {k: v for k, v in head_m.items() if k not in base_m}
                    pre += len(head_m) - len(newm)
                    ev += [{"file": f_, "line": v["line"], "target": v["module"], "path": [f_, v["module"]]} for (f_, _), v in sorted(newm.items())]
                if ev:
                    chain = " -> ".join(ev[0]["path"])
                    F("FAIL", f"{desc or 'forbidden dependency'}: {chain}" + (f" (+{len(ev) - 1} more)" if len(ev) > 1 else ""), ev)
                else:
                    F("PASS", "no new forbidden dependencies" + (f" ({pre} pre-existing, not introduced by this change)" if pre else ""))
                # conservative: new dynamic imports in matching files => cannot prove anything
                unk = []
                for p in paths:
                    pf = ctx.head.files.get(p)
                    if pf and pf.dynamic and glob_match(rule["from"], p):
                        before = len(ctx.base.files[p].dynamic) if ctx.base and p in ctx.base.files else 0
                        if len(pf.dynamic) > before:
                            unk += [{"file": p, "line": ln, "what": w} for ln, w in pf.dynamic]
                if unk:
                    F("UNKNOWN", "dynamic import with non-constant target; cannot verify dependency rule", unk)

            elif t == "required_test":
                files = [p for p in ctx.head.tests() if match_any(rule["paths"], p)]
                if not files:
                    F("FAIL", f"policy requires tests matching {rule['paths']} but none exist", [{"globs": rule["paths"]}])
                else:
                    out.required.append(RequiredTest(pid, sev, on_fail, rule["paths"], files))
                    out.findings.append(Finding("policy", pid, t, "PENDING", sev,
                                                f"{len(files)} required test file(s) must run and pass", [], on_fail))

            elif t == "require_review":
                F("REVIEW_REQUIRED", desc or "human review required", [{"file": p} for p in matched[:20]])

            elif t == "max_changed_lines":
                scope = rule.get("paths")
                total = sum(a + d for p, (a, d) in ctx.numstat.items() if not scope or match_any(scope, p))
                if total > int(rule["max"]):
                    F("FAIL", f"{total} changed lines exceeds limit {rule['max']}", [{"changed_lines": total, "max": rule["max"]}])
                else:
                    F("PASS", f"{total} changed lines (limit {rule['max']})")

            elif t == "test_mode":
                if rule["mode"] == "full":
                    out.force_full.append(f"policy {pid} requires the full suite")
                    F("PASS", "full test suite required by policy")

            elif t == "forbidden_command":
                F("NOT_APPLICABLE", "applies to the agent action gateway only")
    return out
