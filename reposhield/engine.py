"""Verification pipeline: diff -> graph (incremental) -> policy/checks -> test plan -> sandbox -> verdict."""
from __future__ import annotations

import json
import os
import platform
import shutil
import tempfile
import time
import re
import uuid
from pathlib import Path
from importlib import metadata
from dataclasses import dataclass, asdict

from . import __version__, ANALYZER_VERSION, coverage_map, checks as chk
from .analyzer import ParseCache
from .audit import AuditLog
from .contracts import RESULT_SCHEMA_VERSION, VerificationReceipt
from .gitutil import (GitTree, Change, GitError, detect_base, diff_added_lines, diff_changes, diff_numstat,
                      export_tree, git_dir, is_git_repo, merge_base, resolve)
from .graph import Graph
from .models import Finding
from .policy import (POLICY_FILE, EvalContext, evaluate_policies, load_config, policy_hash)
from .sandbox import Limits, base_env, pick_sandbox
from .selector import select_tests
from .util import atomic_write, canonical_json, sha256_hex
from .verdict import aggregate
from . import report as report_mod


@dataclass
class VerifyOptions:
    repo: str = "."
    base: str | None = None
    head: str = "HEAD"
    strategy: str | None = None
    run_tests: bool = True
    always_run_tests: bool = False
    force: bool = False
    trust_head_policy: bool = False
    policy_path: str | None = None
    sandbox: str | None = None
    untrusted_code: bool = False       # code submitted by third parties (webhooks): only run it behind a real isolation boundary
    allow_insecure_sandbox: bool = False
    require_tests: bool = False        # service mode: tests that could not run are UNKNOWN (review), never a quiet PASS


def state_dir_for(repo: str) -> str:
    return os.path.join(git_dir(repo), "reposhield")


def _limits(cfg: dict) -> Limits:
    s, v = cfg["sandbox"], cfg["verification"]
    return Limits(timeout_seconds=int(v["timeout_seconds"]), memory_mb=int(s["memory_mb"]), cpus=s["cpus"],
                  pids=int(s["pids"]), max_output_bytes=int(float(s["max_output_mb"]) * 1024 * 1024),
                  network=bool(s["network"]), image=s["image"])


def _base_graph(repo: str, sha: str, state: str, cache: ParseCache) -> tuple[Graph, bool, float]:
    t = time.time()
    # Mutable graph payloads can suppress findings too. Rebuild until authenticated
    # persistence exists; preserve incremental head updates and in-memory parsing.
    g = Graph.build(GitTree(repo, sha), cache)
    return g, False, time.time() - t


MAX_REPORT_BYTES = 8 * 1024 * 1024
OUTCOMES = {"passed", "failed", "error", "skipped", "xfailed", "xpassed", "incomplete"}


def load_test_report(path: str, workspace: str) -> dict | None:
    """The sandbox wrote this file, so treat it as hostile input: no symlinks, bounded size, strict schema."""
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        ws = os.path.realpath(workspace)
        if not os.path.realpath(path).startswith(ws + os.sep):
            return None
        if os.path.getsize(path) > MAX_REPORT_BYTES:
            return None
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    tests, errs, status = data.get("tests"), data.get("collect_errors"), data.get("exitstatus")
    if (not isinstance(tests, dict) or len(tests) > 200_000 or not isinstance(errs, list)
            or not isinstance(status, int) or isinstance(status, bool)):
        return None
    clean = {}
    for name, rec in tests.items():
        if not isinstance(name, str) or not isinstance(rec, dict) or rec.get("outcome") not in OUTCOMES:
            return None
        dur = rec.get("duration", 0)
        clean[name] = {"outcome": rec["outcome"], "duration": float(dur) if isinstance(dur, (int, float)) and not isinstance(dur, bool) else 0.0}
    return {"tests": clean, "collect_errors": [c[:300] for c in errs if isinstance(c, str)][:1000], "exitstatus": status}


def _run_tests(plan, cfg, repo, head_sha, sandbox, limits):
    ws = tempfile.mkdtemp(prefix="reposhield-ws-")
    try:
        export_tree(repo, head_sha, ws)
        coverage_map.install_plugin(ws)
        cmd = list(cfg["verification"]["test_command"])
        if cmd and cmd[0] in ("python", "python3"):
            cmd[0] = sandbox.python
        argv = cmd + ["-q", "-p", "no:cacheprovider", "-p", "rs_pytest_plugin"]
        if not plan.full:
            argv += [t.path for t in plan.tests]
        res = sandbox.run(argv, ws, env={"RS_RESULT_PATH": ".reposhield/out/results.json"}, limits=limits)
        report = load_test_report(os.path.join(ws, ".reposhield", "out", "results.json"), ws)
        return res, report
    finally:
        if not os.environ.get("REPOSHIELD_KEEP_WORKSPACE"):
            shutil.rmtree(ws, ignore_errors=True)


def _test_findings(res, report, plan, limits) -> tuple[list[Finding], dict]:
    F = lambda r, sev, msg, ev=None: Finding("tests", "test-run", "tests", r, sev, msg, ev or [])
    summary = {"executed": 0, "passed": 0, "failed": 0, "skipped": 0, "exit_code": res.exit_code,
               "duration_ms": res.duration_ms, "timed_out": res.timed_out}
    if res.timed_out:
        return [F("FAIL", "high", f"test run exceeded {limits.timeout_seconds}s and was killed")], summary
    if report is None:
        return [F("UNKNOWN", "high", f"no test report produced (exit code {res.exit_code}); tests NOT verified",
                  [{"stderr_tail": res.stderr[-500:], "stdout_tail": res.stdout[-500:]}])], summary
    tests = report.get("tests", {})
    failed = sorted(n for n, r in tests.items() if r["outcome"] in ("failed", "error"))
    skipped = [n for n, r in tests.items() if r["outcome"] in ("skipped", "xfailed", "xpassed", "incomplete")]
    summary.update(executed=len(tests), passed=sum(r["outcome"] == "passed" for r in tests.values()),
                   failed=len(failed), skipped=len(skipped))
    out = []
    if report.get("collect_errors"):
        out.append(F("FAIL", "high", f"{len(report['collect_errors'])} collection error(s)",
                     [{"file": c} for c in report["collect_errors"][:20]] + [{"stdout_tail": res.stdout[-800:]}]))
    if failed:
        out.append(F("FAIL", "high", f"{len(failed)} of {len(tests)} tests failed",
                     [{"test": n} for n in failed[:20]] + [{"stdout_tail": res.stdout[-800:]}]))
    if report.get("exitstatus") != res.exit_code:
        out.append(F("UNKNOWN", "high", "pytest exit status disagrees with the report; result not trusted"))
    if res.exit_code != 0 and not failed and not report.get("collect_errors"):
        out.append(F("UNKNOWN", "high", f"pytest did not complete successfully (exit {res.exit_code})"))
    observed_files = {n.split("::", 1)[0] for n in tests}
    missing = sorted(t.path for t in plan.tests if t.path not in observed_files)
    if missing:
        out.append(F("UNKNOWN", "high", "selected test files have no collected evidence",
                     [{"file": p} for p in missing[:20]]))
    if any(r["outcome"] == "incomplete" for r in tests.values()):
        out.append(F("UNKNOWN", "high", "test observations lack a completed call phase"))
    if not out:
        if not summary["passed"]:
            out.append(F("UNKNOWN", "high", "no ordinary passing tests; tests NOT verified"))
        else:
            out.append(F("PASS", "high", f"{summary['passed']} passed, {len(skipped)} skipped, 0 failed"))
    return out, summary


def _finalize_required(findings, required, report, ran: bool):
    for req in required:
        idx = next((i for i, f in enumerate(findings) if f.result == "PENDING" and
                    f.rule_type == "required_test" and f.rule_id == req.policy_id), None)
        if idx is None:
            continue
        if not ran or report is None:
            nf = Finding("policy", req.policy_id, "required_test", "UNKNOWN", req.severity,
                         "required tests were not executed; cannot verify", [{"files": req.files[:10]}], req.on_fail)
        else:
            tests = report["tests"]
            missing, failing = [], []
            for f in req.files:
                mine = {n: r for n, r in tests.items() if n.split("::", 1)[0] == f}
                if not any(r["outcome"] == "passed" for r in mine.values()):
                    missing.append(f)
                failing += [n for n, r in mine.items() if r["outcome"] in ("failed", "error")]
            if missing or failing:
                nf = Finding("policy", req.policy_id, "required_test", "FAIL" if failing else "UNKNOWN", req.severity,
                             (f"required files lack ordinary passing tests: {', '.join(missing[:3])}" if missing else "") +
                             (f"{' ; ' if missing else ''}required tests failed: {', '.join(failing[:3])}" if failing else ""),
                             [{"file": m, "issue": "no ordinary passing test"} for m in missing] + [{"test": n} for n in failing[:10]],
                             req.on_fail)
            else:
                nf = Finding("policy", req.policy_id, "required_test", "PASS", req.severity,
                             f"{len(req.files)} required test file(s) executed and passed", [], req.on_fail)
        findings[idx] = nf


def _implementation_digest() -> str:
    root = Path(__file__).parent
    return sha256_hex(canonical_json({p.relative_to(root).as_posix(): sha256_hex(p.read_bytes())
                                    for p in sorted(root.rglob("*.py"))
                                    if "demo_data" not in p.parts}))


def _input_context(opts, repo, head_sha, base_sha, mb, cfg, text, source, errs, sandbox, strategy):
    options = asdict(opts)
    # Refs have already been resolved. force changes attempt intent, not evidence.
    for name in ("repo", "head", "base", "force"):
        options.pop(name)
    image = cfg["sandbox"]["image"]
    pinned = bool(re.fullmatch(r"(?:[^\s]+@)?sha256:[0-9a-f]{64}", image))
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "repository": os.path.normcase(os.path.realpath(repo)),
        "head": head_sha, "base": base_sha, "merge_base": mb, "execution_tree": head_sha,
        "policy_hash": policy_hash(cfg), "policy_text_hash": sha256_hex(text or ""),
        "policy_source": source, "policy_errors": errs, "options": options,
        "analyzer": ANALYZER_VERSION, "tool": __version__,
        "implementation_digest": _implementation_digest(),
        "python": platform.python_version(), "platform": platform.platform(),
        "runtime_packages": sorted((d.metadata["Name"], d.version) for d in metadata.distributions()
                                   if d.metadata["Name"]),
        "sandbox": sandbox.name, "runner_python": sandbox.python,
        "runner_image": image, "runner_image_digest": image.split("@")[-1] if pinned else None,
        "environment_policy": {
            "profile": "scrubbed-subprocess-v1" if sandbox.name == "subprocess" else "docker-explicit-env-v1",
            # Use a stable workspace marker, never attempt-specific temp paths, and
            # hash inherited Windows bootstrap values instead of exposing them.
            "bootstrap_digest": sha256_hex(canonical_json(base_env("<workspace>")))
                if sandbox.name == "subprocess" else None,
        },
        "isolation_profile": sandbox.isolation(_limits(cfg)),
        "limits": asdict(_limits(cfg)), "strategy": strategy,
        "assurance_mode": "enforced" if opts.untrusted_code and not opts.allow_insecure_sandbox else "development",
        "evidence_requirements": {"require_tests": opts.require_tests,
                                  "required_test_semantics": "ordinary-pass-per-file-v2"},
        "cache_policy": "disabled-until-authenticated-persistence",
        "coverage_policy": "disabled-unsigned-coverage",
    }


def verify(opts: VerifyOptions) -> dict:
    t_start = time.time()
    repo = os.path.abspath(opts.repo)
    if not is_git_repo(repo):
        raise GitError(f"{repo} is not a git repository")
    state = state_dir_for(repo)
    base_ref = opts.base or detect_base(repo)
    head_sha, base_sha = resolve(repo, opts.head), resolve(repo, base_ref)
    try:
        mb = merge_base(repo, base_sha, head_sha)
    except GitError:
        raise GitError(f"base ({base_ref}) and head ({opts.head}) share no common ancestor in this clone - "
                       "shallow clone? fetch full history (e.g. `git fetch --unshallow` or CI `fetch-depth: 0`)")
    timings, findings = {}, []

    # ---- trusted policy: from the BASE branch, never from the change under test ----
    base_tree, head_tree = GitTree(repo, base_sha), GitTree(repo, head_sha)
    text, source = None, "none"
    if opts.policy_path:
        with open(opts.policy_path, encoding="utf-8") as fh:
            text, source = fh.read(), f"file:{opts.policy_path}"
    else:
        raw = base_tree.read(POLICY_FILE)
        if raw is not None:
            text, source = raw.decode("utf-8", "replace"), f"base:{base_sha[:8]}"
        else:
            raw = head_tree.read(POLICY_FILE)
            if raw is not None:
                text = raw.decode("utf-8", "replace")
                source = "head(trusted via flag)" if opts.trust_head_policy else "head(UNTRUSTED)"
                if not opts.trust_head_policy:
                    findings.append(Finding("check", "policy-introduced", "policy_tamper", "REVIEW_REQUIRED", "high",
                                            f"{POLICY_FILE} does not exist on the base branch; the policy comes from the change itself "
                                            "and cannot be trusted. Merge the policy first or pass --trust-head-policy.",
                                            [{"file": POLICY_FILE}]))
    # Proposed policy may be displayed/hashed, but cannot configure its own runner.
    cfg, errs = load_config(text) if text is not None and source != "head(UNTRUSTED)" else load_config("version: 1")
    phash = policy_hash(cfg)
    if text is None:
        findings.append(Finding("check", "policy-missing", "policy", "NOT_APPLICABLE", "low",
                                f"no {POLICY_FILE} found; only built-in checks ran"))
    if errs:
        findings.append(Finding("policy", "policy-invalid", "policy", "FAIL", "critical",
                                "policy file is invalid (fail-closed): " + "; ".join(errs[:3]), [{"error": e} for e in errs]))

    strategy = opts.strategy or cfg["verification"]["strategy"]
    sandbox = pick_sandbox(opts.sandbox or cfg["sandbox"]["backend"], cfg["sandbox"]["image"])
    context = _input_context(opts, repo, head_sha, base_sha, mb, cfg, text, source, errs, sandbox, strategy)
    key = canonical_json(context)
    run_id = "rs_" + sha256_hex(key)
    attempt_id = "attempt_" + uuid.uuid4().hex
    run_dir = os.path.join(state, "runs", run_id, attempt_id)
    result_path = os.path.join(run_dir, "result.json")
    # A self-consistent chain does not authenticate result bytes or detect truncation.
    # No gate reuse (even with force=False) until RS2 08 signed persistence exists.
    os.makedirs(run_dir)
    audit = AuditLog(os.path.join(run_dir, "events.jsonl"), run_id)
    audit.append("RUN_CREATED", "reposhield", {"head": head_sha, "base": base_sha, "merge_base": mb,
                 "attempt_id": attempt_id, "idempotency_key": sha256_hex(key)})
    audit.append("POLICY_LOADED", "reposhield", {"source": source, "policy_hash": phash, "errors": errs})

    # ---- diff ----
    t = time.time()
    changes = diff_changes(repo, mb, head_sha)
    numstat, added = diff_numstat(repo, mb, head_sha), diff_added_lines(repo, mb, head_sha)
    timings["diff"] = int((time.time() - t) * 1000)
    audit.append("DIFF_COMPUTED", "reposhield", {"files": len(changes), "paths": [c.path for c in changes][:200]})

    # ---- graph: cached base graph + incremental update for the head ----
    cache = ParseCache()  # disk parse payloads are unauthenticated too
    base_g, base_cached, base_s = _base_graph(repo, mb, state, cache)
    t = time.time()
    head_g = base_g.clone()
    py_changed = {c.path for c in changes if c.path.endswith(".py") and c.status != "D"}
    py_removed = {c.path for c in changes if c.path.endswith(".py") and c.status == "D"}
    upd = head_g.update(head_tree, py_changed, py_removed, cache)
    cache.save()
    timings["graph_incremental"] = int((time.time() - t) * 1000)
    timings["graph_base"] = int(base_s * 1000)
    graph_info = {"files": len(head_g.files), "edges": head_g.edge_count(), "tests": len(head_g.tests()),
                  "mode": "incremental", "updated": len(py_changed | py_removed), "reparsed": upd["parsed"],
                  "reused": upd["reused"], "base_graph_cached": base_cached}
    audit.append("GRAPH_UPDATED", "reposhield", graph_info)

    # ---- deterministic checks & policies ----
    t = time.time()
    tamper = chk.policy_tamper(changes, source)
    if tamper:
        findings.append(tamper)
    findings.append(chk.syntax_check(head_g, changes))
    findings.append(chk.secret_scan(added))
    findings.append(chk.dependency_check(changes, added))
    ti = chk.test_integrity(head_g, base_g, changes, cfg["verification"]["test_integrity"])
    if ti:
        findings.append(ti)
    outcome = evaluate_policies(cfg, EvalContext(changes, head_g, base_g, numstat, added))
    findings += outcome.findings
    timings["policy_and_checks"] = int((time.time() - t) * 1000)
    audit.append("POLICY_EVALUATED", "reposhield", {"findings": [{"id": f.rule_id, "type": f.rule_type, "result": f.result} for f in findings]})
    for f in findings:
        if f.effect == "BLOCK":
            audit.append("POLICY_VIOLATION", "reposhield", {"id": f.rule_id, "message": f.message})

    # ---- test selection ----
    cov = None  # do not let mutable coverage prune required transitive evidence
    force_full = list(outcome.force_full)
    if cfg["verification"]["test_mode"] == "full":
        force_full.append("verification.test_mode is 'full'")
    plan = select_tests(head_g, base_g, changes, strategy=strategy, coverage=cov,
                        ignore_paths=cfg["verification"]["ignore_paths"], force_full=force_full,
                        required_files=[f for r in outcome.required for f in r.files])
    audit.append("TEST_PLAN_CREATED", "reposhield", {"mode": plan.mode, "selected": len(plan.tests), "total": plan.total_tests,
                                                    "strategy": plan.strategy, "fallback_reasons": plan.fallback_reasons})

    # ---- sandboxed execution ----
    limits = _limits(cfg)
    iso = sandbox.isolation(limits)
    blocked_early = any(f.effect == "BLOCK" for f in findings)
    tests_info: dict = {"status": "NOT_RUN", "reason": ""}
    report = None
    if not opts.run_tests:
        tests_info["reason"] = "disabled (--no-tests)"
    elif plan.mode == "NONE":
        tests_info = {"status": "NOT_NEEDED", "reason": "no changed file can affect any test"}
        findings.append(Finding("tests", "test-run", "tests", "PASS", "high", "no tests needed for this change"))
    elif blocked_early and not opts.always_run_tests:
        tests_info["reason"] = "skipped: a blocking finding already exists (use --always-run-tests to run anyway)"
    elif opts.untrusted_code and not iso.get("security_boundary") and not opts.allow_insecure_sandbox:
        tests_info["reason"] = (f"submitted code was NOT executed: the '{sandbox.name}' sandbox is not a security boundary "
                                "(use the docker backend, or --insecure-dev-sandbox for local experiments)")
    elif cfg["sandbox"]["require_isolation"] and not iso.get("security_boundary"):
        tests_info["reason"] = "sandbox backend is not a security boundary and policy requires isolation"
        findings.append(Finding("tests", "sandbox-isolation", "sandbox", "UNKNOWN", "high",
                                "policy requires an isolating sandbox (docker); tests were not executed"))
    elif sandbox.name == "docker" and not context["runner_image_digest"] and (
            (opts.untrusted_code and not opts.allow_insecure_sandbox) or cfg["sandbox"]["require_isolation"]):
        tests_info["reason"] = "enforced execution requires an immutable runner image digest"
        findings.append(Finding("tests", "runner-image", "sandbox", "UNKNOWN", "high", tests_info["reason"]))
    else:
        audit.append("SANDBOX_STARTED", sandbox.name, {"isolation": iso, "tests": len(plan.tests), "full": plan.full})
        res, report = _run_tests(plan, cfg, repo, head_sha, sandbox, limits)
        tfs, summ = _test_findings(res, report, plan, limits)
        findings += tfs
        tests_info = {"status": "RAN", **summ, "backend": sandbox.name, "isolation": res.isolation,
                      "output_truncated": res.truncated}
        timings["tests"] = res.duration_ms
        audit.append("SANDBOX_FINISHED", sandbox.name, {k: v for k, v in summ.items()})
    if (opts.require_tests or opts.untrusted_code) and plan.mode != "NONE" and tests_info["status"] != "RAN" and not blocked_early:
        findings.append(Finding("tests", "tests-not-executed", "tests", "UNKNOWN", "high",
                                "tests could not be executed safely: " + (tests_info.get("reason") or "unknown reason")))
    _finalize_required(findings, outcome.required, report, tests_info["status"] == "RAN")

    # ---- verdict ----
    verdict, summary = aggregate(findings)
    audit.append("VERDICT_ISSUED", "reposhield", {"verdict": verdict, "summary": summary})
    imp = head_g.impact([p for p in py_changed])
    impact = [{"file": p, "distance": i.distance, "confidence": i.conf, "via": i.via}
              for p, i in sorted(imp.items(), key=lambda kv: (kv[1].distance, kv[0])) if i.distance > 0]
    timings["total"] = int((time.time() - t_start) * 1000)
    result = {
        "schema_version": RESULT_SCHEMA_VERSION, "attempt_id": attempt_id,
        "execution_state": "failed-infrastructure" if tests_info["status"] == "RAN" and (
            report is None or tests_info.get("exit_code") in (None, 3, 4) or tests_info.get("timed_out")) else "completed",
        "mode": "DEVELOPMENT EXECUTION" if tests_info["status"] == "RAN" else "VERIFICATION ONLY",
        "run_id": run_id, "verdict": verdict, "summary": summary, "cached": False,
        "fingerprint": {**context, "effective_strategy": plan.strategy, "idempotency_key": sha256_hex(key)},
        "project": cfg["project"]["name"],
        "changes": [{"status": c.status, "path": c.path, "added": numstat.get(c.path, (0, 0))[0], "deleted": numstat.get(c.path, (0, 0))[1]} for c in changes],
        "graph": graph_info, "impact": impact[:300], "impact_total": len(impact),
        "plan": plan.to_dict(), "tests": tests_info,
        "findings": [f.to_dict() for f in findings],
        "timings_ms": timings,
    }
    VerificationReceipt.model_validate({k: result[k] for k in (
        "schema_version", "run_id", "attempt_id", "verdict", "execution_state", "mode")} |
        {"input_digest": sha256_hex(key)})
    audit.append("RUN_COMPLETED", "reposhield", {"verdict": verdict})
    result["audit"] = {"events": audit.seq, "head_hash": audit.head_hash}
    events = [json.loads(l) for l in open(audit.path, encoding="utf-8")]
    result["events"] = [{"seq": e["seq"], "ts": e["ts"], "type": e["type"], "actor": e["actor"]} for e in events]
    atomic_write(os.path.join(run_dir, "report.md"), report_mod.markdown(result))
    atomic_write(os.path.join(run_dir, "report.html"), report_mod.html_report(result, events))
    atomic_write(result_path, json.dumps(result, indent=2))          # written last: its presence marks a complete run
    result["run_dir"] = run_dir
    return result


def analyze(repo: str, ref: str = "HEAD") -> dict:
    repo = os.path.abspath(repo)
    sha = resolve(repo, ref)
    g = Graph.build(GitTree(repo, sha), ParseCache())
    funcs = sum(1 for f in g.files.values() for d in f.defs if d.kind in ("function", "method"))
    return {"ref": ref, "sha": sha, "python_files": len(g.files), "test_files": len(g.tests()),
            "tests": sum(len(f.tests) for f in g.files.values()), "functions": funcs, "edges": g.edge_count(),
            "unparseable": sorted(p for p, f in g.files.items() if not f.ok),
            "dynamic_imports": sum(len(f.dynamic) for f in g.files.values())}


def build_baseline(repo: str, ref: str = "HEAD", sandbox_name: str = "auto") -> dict:
    repo = os.path.abspath(repo)
    sha = resolve(repo, ref)
    state = state_dir_for(repo)
    cfg, _ = load_config(GitTree(repo, sha).read(POLICY_FILE).decode() if GitTree(repo, sha).read(POLICY_FILE) else "version: 1")
    sb = pick_sandbox(sandbox_name if sandbox_name != "auto" else cfg["sandbox"]["backend"])
    ws = tempfile.mkdtemp(prefix="reposhield-base-")
    try:
        export_tree(repo, sha, ws)
        mapping = coverage_map.collect(ws, sb, _limits(cfg))
    finally:
        shutil.rmtree(ws, ignore_errors=True)
    if mapping is None:
        raise RuntimeError("could not collect coverage (is `coverage` installed in the runner?)")
    coverage_map.save(os.path.join(state, "cache", f"coverage-{sha}.json"), mapping)
    return {"sha": sha, "source_files_mapped": len(mapping), "backend": sb.name}
