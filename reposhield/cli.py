from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

from . import __version__
from .actions import Denied, authorize, canonical_action, execute, load_key
from .audit import AuditLog, read_events, verify_chain
from .engine import VerifyOptions, analyze, build_baseline, state_dir_for, verify
from .gitutil import GitError, GitTree, resolve
from .graph import Graph
from .analyzer import ParseCache
from .policy import POLICY_FILE, STARTER, load_config, policy_hash
from .sandbox import Limits, pick_sandbox

EXIT = {"PASS": 0, "BLOCK": 1, "REVIEW_REQUIRED": 2}
C = {"PASS": "\033[32m", "BLOCK": "\033[31m", "REVIEW_REQUIRED": "\033[33m", "dim": "\033[2m", "off": "\033[0m"}


def _c(txt, key, tty):
    return f"{C[key]}{txt}{C['off']}" if tty else txt


def _print_result(r: dict, fmt: str):
    if fmt == "json":
        print(json.dumps(r, indent=2))
        return
    from .report import markdown
    if fmt == "markdown":
        print(markdown(r))
        return
    tty = sys.stdout.isatty()
    p, t = r["plan"], r["tests"]
    print(f"\n RepoShield  {_c(r['verdict'], r['verdict'], tty)}   {_c('(cached)', 'dim', tty) if r.get('cached') else ''}")
    print(f" {r['summary']}\n")
    print(f" {r.get('mode', 'VERIFICATION ONLY')} | execution: {r.get('execution_state', 'unknown-outcome')}\n")
    for f in r["findings"]:
        if f["effect"] in ("BLOCK", "REVIEW", "INFO"):
            mark = {"BLOCK": "✗", "REVIEW": "!", "INFO": "i"}[f["effect"]]
            print(f"  {mark} [{f['severity']}] {f['rule_id']}: {f['message']}")
            for ev in f["evidence"][:4]:
                loc = f"{ev['file']}:{ev['line']}" if "file" in ev and "line" in ev else ev.get("file") or ev.get("test") or ""
                via = f"  via {' -> '.join(ev['path'])}" if isinstance(ev.get("path"), list) and len(ev["path"]) > 2 else ""
                if loc:
                    print(f"      {loc}{via}")
    passed = [f for f in r["findings"] if f["result"] == "PASS" and f["source"] == "policy"]
    na = [f for f in r["findings"] if f["result"] == "NOT_APPLICABLE" and f["source"] == "policy"]
    print(f"\n  policies: {len(passed)} passed, {len(na)} not applicable")
    print(f"  graph:    {r['graph']['files']} files, {r['graph']['edges']} edges; incremental update touched "
          f"{r['graph']['updated']} file(s) ({r['graph']['reparsed']} parsed, rest reused)")
    print(f"  impact:   {r['impact_total']} file(s) potentially affected")
    if t["status"] == "RAN":
        print(f"  tests:    {p['selected']}/{p['total']} files selected ({p['reduction_pct']}% fewer, mode {p['mode']}); "
              f"{t['passed']} passed, {t['failed']} failed, {t['skipped']} skipped in {t['duration_ms']} ms [{t['backend']}]")
    else:
        print(f"  tests:    {t['status']} - {t.get('reason', '')}")
    for fr in p["fallback_reasons"][:3]:
        print(f"            full-suite fallback: {fr}")
    if r.get("run_dir"):
        print(f"\n  report:   {os.path.join(r['run_dir'], 'report.html')}")
    print(f"  run:      {r['run_id']}   audit head {r['audit']['head_hash'][:12]}\n")


def cmd_init(a):
    path = os.path.join(a.repo, POLICY_FILE)
    if os.path.exists(path) and not a.force:
        print(f"{path} already exists (use --force)")
        return 1
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(STARTER)
    print(f"wrote {path}")
    return 0


def cmd_analyze(a):
    r = analyze(a.repo, a.ref)
    print(json.dumps(r, indent=2) if a.json else "\n".join(f"{k:>16}: {v}" for k, v in r.items()))
    return 0


def cmd_policy_validate(a):
    path = a.file or os.path.join(a.repo, POLICY_FILE)
    with open(path, encoding="utf-8") as fh:
        cfg, errs = load_config(fh.read())
    if errs:
        print("INVALID:\n  " + "\n  ".join(errs))
        return 1
    print(f"OK  {len(cfg['policies'])} polic{'y' if len(cfg['policies']) == 1 else 'ies'}  hash {policy_hash(cfg)[:12]}")
    return 0


def cmd_graph(a):
    repo = os.path.abspath(a.repo)
    g = Graph.build(GitTree(repo, resolve(repo, a.ref)), ParseCache())
    if a.impact:
        for p, i in sorted(g.impact(a.impact).items(), key=lambda kv: (kv[1].distance, kv[0])):
            print(f"{i.distance}  {p:<40} conf={i.conf:.2f}  {' -> '.join(i.via)}")
    elif a.format == "dot":
        print("digraph reposhield {\n  rankdir=LR; node [shape=box, fontsize=10];")
        for es in g.out.values():
            for e in es:
                print(f'  "{e.src}" -> "{e.dst}"' + (' [style=dashed]' if e.kind != "import" else ""))
        print("}")
    else:
        print(json.dumps({"nodes": sorted(g.files), "edges": [[e.src, e.dst, e.kind, e.conf, e.line] for es in g.out.values() for e in es]}, indent=1))
    return 0


def _opts(a, **kw) -> VerifyOptions:
    return VerifyOptions(repo=a.repo, base=a.base, head=a.head, strategy=getattr(a, "strategy", None),
                         force=getattr(a, "force", False), trust_head_policy=getattr(a, "trust_head_policy", False),
                         policy_path=getattr(a, "policy", None), sandbox=getattr(a, "sandbox", None), **kw)


def cmd_verify(a):
    r = verify(_opts(a, run_tests=not a.no_tests, always_run_tests=a.always_run_tests))
    _print_result(r, a.format)
    return EXIT[r["verdict"]]


def cmd_test_plan(a):
    r = verify(_opts(a, run_tests=False))
    p = r["plan"]
    print(f"mode {p['mode']} · strategy {p['strategy']} · {p['selected']}/{p['total']} test files ({p['reduction_pct']}% fewer)")
    for fr in p["fallback_reasons"]:
        print(f"  fallback: {fr}")
    for t in p["tests"][:50] if p["mode"] != "FULL" else []:
        why = "; ".join(f"{x.get('kind')}" + (f" ← {x['changed']}" if "changed" in x else "") + (f" ({' → '.join(x['path'])})" if x.get("path") else "") for x in t["reasons"][:2])
        print(f"  [{t['confidence']:<6}] {t['path']}   {why}")
    return 0


def cmd_baseline(a):
    print(json.dumps(build_baseline(a.repo, a.ref, a.sandbox or "auto"), indent=2))
    return 0


def _run_dir(a):
    if os.path.isdir(a.run):
        return a.run
    return os.path.join(state_dir_for(a.repo), "runs", a.run)


def cmd_audit(a):
    d = _run_dir(a)
    path = os.path.join(d, "events.jsonl")
    if a.what == "verify":
        ok, msg = verify_chain(path)
        print(("OK   " if ok else "TAMPERED  ") + msg)
        return 0 if ok else 1
    for e in read_events(path):
        print(f"{e['seq']:>3}  {e['type']:<20} {e['actor']:<12} {e['hash'][:10]}  {json.dumps(e['data'])[:110]}")
    return 0


def _gateway(a):
    repo = os.path.abspath(a.repo)
    with open(a.policy or os.path.join(repo, POLICY_FILE), encoding="utf-8") as fh:
        cfg, errs = load_config(fh.read())
    if errs:
        raise SystemExit("invalid policy: " + "; ".join(errs))
    state = state_dir_for(repo)
    audit = AuditLog(os.path.join(state, "gateway-events.jsonl"), "gateway")
    return repo, cfg, policy_hash(cfg), load_key(state), state, audit


def cmd_action(a):
    repo, cfg, ph, key, state, audit = _gateway(a)
    action = canonical_action(a.cmd, a.cwd)
    try:
        if a.what == "authorize":
            print(authorize(action, cfg, ph, key, repo, audit, a.ttl))
            return 0
        res = execute(a.token, action, cfg, ph, key, repo, state, pick_sandbox(a.sandbox or "auto"), audit)
        sys.stdout.write(res.stdout)
        sys.stderr.write(res.stderr)
        return res.exit_code if res.exit_code is not None else 1
    except Denied as e:
        print(f"DENIED: {e}", file=sys.stderr)
        return 1


def cmd_doctor(a):
    from .doctor import run_doctor
    return run_doctor(a.sandbox or "auto")


def cmd_serve(a):
    try:
        import uvicorn
        from .server.app import create_app
        from .server.config import ServerConfig
    except ImportError:
        print("the service needs extra packages:  pip install -e \".[server]\"", file=sys.stderr)
        return 3
    cfg = ServerConfig(data_dir=a.data_dir, host=a.host, port=a.port, workers=a.workers, sandbox=a.sandbox,
                       allowed_repos=a.allow_repo or [], local_roots=a.allow_local or [], public_url=a.public_url,
                       insecure_dev_sandbox=a.insecure_dev_sandbox)
    if cfg.database_url:
        print("RepoShield PostgreSQL coordinator: execution disabled; start the separate worker process.")
        # OAuth callback queries contain short-lived codes. Do not access-log them.
        uvicorn.run(create_app(cfg), host=a.host, port=a.port, log_level="info", access_log=False)
        return 0
    if a.host not in ("127.0.0.1", "localhost", "::1") and not cfg.api_token:
        print("refusing to listen on a non-loopback address without REPOSHIELD_API_TOKEN set", file=sys.stderr)
        return 3
    if not a.legacy_dev_server:
        print("Set REPOSHIELD_DATABASE_URL and REPOSHIELD_IDENTITIES_FILE, or explicitly use --legacy-dev-server.", file=sys.stderr)
        return 3
    print(f"RepoShield service on http://{a.host}:{a.port}  (data: {os.path.abspath(a.data_dir)})")
    print(f"  auth: {'API token required' if cfg.api_token else 'none (loopback only)'}"
          f" | webhook: {'enabled' if cfg.webhook_secret else 'disabled (set GITHUB_WEBHOOK_SECRET)'}"
          f" | local repos: {', '.join(a.allow_local) if a.allow_local else 'disabled (--allow-local ROOT)'}"
          f" | GitHub reporting: {'on' if cfg.github_token else 'off (set GITHUB_TOKEN)'}")
    if a.sandbox != "docker" and not a.insecure_dev_sandbox:
        print("  note: webhook-submitted code will NOT be executed without the docker sandbox (static checks only -> REVIEW_REQUIRED)")
    uvicorn.run(create_app(cfg), host=a.host, port=a.port, log_level="info")
    return 0


def cmd_demo(a):
    from .demo import EXPECTED, build_demo
    info = build_demo(a.dir, a.force)
    print(f"demo repo created at {info['path']}\n\nTry:\n  cd {info['path']}")
    for b, desc in info["branches"].items():
        print(f"  reposhield verify --base main --head {b:<22} # agent {desc} -> expect {EXPECTED[b]}")
    return 0


def cmd_showcase(a):
    """Verify every pr/* branch and print one summary table + an HTML index (for presentations)."""
    import html as _h
    import webbrowser
    from .demo import EXPECTED
    from .gitutil import git
    repo = os.path.abspath(a.repo)
    branches = [b for b in git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/pr/").split() if b]
    if not branches:
        print("no pr/* branches found - run `reposhield demo` first and cd into it")
        return 1
    rows = []
    print(f"\n{'branch':<24}{'verdict':<17}{'tests':<12}{'time':>6}  ok")
    print("-" * 64)
    for b in branches:
        r = verify(VerifyOptions(repo=repo, base=a.base or "main", head=b, sandbox=a.sandbox, force=True))
        p = r["plan"]
        ran = f"{p['selected']}/{p['total']}" if r["tests"]["status"] == "RAN" else r["tests"]["status"].lower().replace("_", " ")
        exp = EXPECTED.get(b, "-")
        mark = "-" if exp == "-" else ("yes" if exp == r["verdict"] else "DIFF")
        print(f"{b:<24}{r['verdict']:<17}{ran:<12}{r['timings_ms']['total'] / 1000:>5.1f}s  {mark}")
        rows.append((b, r, exp, ran))
    if any(x[2] not in ("-", x[1]["verdict"]) for x in rows):
        print("\nSome verdicts differ from the expected ones (column 'ok').")
    from .report import gallery_html
    from .demo import SCENARIOS
    story = lambda b: SCENARIOS[b][1] if b in SCENARIOS else ""
    gallery = [{"branch": b, "story": story(b), "expected": exp, "result": r,
                "report_uri": pathlib.Path(r["run_dir"], "report.html").as_uri()} for b, r, exp, _ in rows]
    index = os.path.join(state_dir_for(repo), "showcase.html")
    with open(index, "w", encoding="utf-8") as fh:
        fh.write(gallery_html(gallery, __version__))
    print(f"\nHTML index: {index}")
    if a.open:
        webbrowser.open(pathlib.Path(index).as_uri())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="reposhield", description="Deterministic verification for AI-generated code changes.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("-C", "--repo", default=".", help="path to the git repository (default .)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="write a starter .reposhield.yml"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("analyze", help="repository statistics"); s.add_argument("--ref", default="HEAD"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_analyze)
    s = sub.add_parser("policy", help="policy tools"); s.add_argument("what", choices=["validate"]); s.add_argument("--file"); s.set_defaults(fn=cmd_policy_validate)
    s = sub.add_parser("graph", help="dependency graph / impact"); s.add_argument("--ref", default="HEAD")
    s.add_argument("--format", choices=["json", "dot"], default="json"); s.add_argument("--impact", nargs="+", metavar="FILE"); s.set_defaults(fn=cmd_graph)

    def common(s):
        s.add_argument("--base"); s.add_argument("--head", default="HEAD"); s.add_argument("--strategy", choices=["safe", "balanced"])
        s.add_argument("--policy", help="use this policy file instead of the base branch's"); s.add_argument("--trust-head-policy", action="store_true")
        s.add_argument("--sandbox", choices=["auto", "subprocess", "docker"]); s.add_argument("--force", action="store_true")
    s = sub.add_parser("verify", help="verify a change (base..head)"); common(s)
    s.add_argument("--no-tests", action="store_true"); s.add_argument("--always-run-tests", action="store_true")
    s.add_argument("--format", choices=["text", "json", "markdown"], default="text"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("test-plan", help="show which tests would run"); common(s); s.set_defaults(fn=cmd_test_plan)
    s = sub.add_parser("baseline", help="build the coverage-based test->code map"); s.add_argument("--ref", default="HEAD"); s.add_argument("--sandbox"); s.set_defaults(fn=cmd_baseline)
    s = sub.add_parser("audit", help="inspect / verify a run's audit chain"); s.add_argument("what", choices=["verify", "show"]); s.add_argument("run"); s.set_defaults(fn=cmd_audit)
    s = sub.add_parser("action", help="agent action gateway"); s.add_argument("what", choices=["authorize", "exec"])
    s.add_argument("--cmd", required=True); s.add_argument("--cwd", default="."); s.add_argument("--ttl", type=int); s.add_argument("--token")
    s.add_argument("--policy"); s.add_argument("--sandbox"); s.set_defaults(fn=cmd_action)
    s = sub.add_parser("showcase", help="verify every pr/* branch and show a summary table"); s.add_argument("--base"); s.add_argument("--sandbox")
    s.add_argument("--open", action="store_true", help="open the HTML index in a browser"); s.set_defaults(fn=cmd_showcase)
    s = sub.add_parser("serve", help="run the REST API + GitHub webhook + dashboard (needs the [server] extra)")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8080)
    s.add_argument("--data-dir", default="reposhield-data"); s.add_argument("--workers", type=int, default=2)
    s.add_argument("--sandbox", choices=["auto", "subprocess", "docker"], default="auto")
    s.add_argument("--allow-local", action="append", metavar="ROOT", help="allow verifying local repos under ROOT (repeatable)")
    s.add_argument("--allow-repo", action="append", metavar="OWNER/NAME", help="webhook allow-list (repeatable, or '*')")
    s.add_argument("--public-url", help="externally reachable base URL, used for status links")
    s.add_argument("--insecure-dev-sandbox", action="store_true", help="execute webhook-submitted code WITHOUT an isolating sandbox (local experiments only)")
    s.add_argument("--legacy-dev-server", action="store_true", help="use the old SQLite/in-process development service; not controlled execution")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("doctor", help="check the environment and prove what the sandbox enforces"); s.add_argument("--sandbox", choices=["auto", "subprocess", "docker"]); s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("demo", help="create a demo repository with sample AI-agent PR branches"); s.add_argument("dir", nargs="?", default="reposhield-demo")
    s.add_argument("--force", action="store_true", help="replace the folder even if it does not look like a demo"); s.set_defaults(fn=cmd_demo)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (GitError, OSError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
