"""Server-rendered dashboard (no JS build step). Every dynamic value is HTML-escaped."""
from __future__ import annotations

import html
import json
import time

COLORS = {"PASS": "#1a7f37", "BLOCK": "#cf222e", "REVIEW_REQUIRED": "#bf8700", "queued": "#656d76", "running": "#0969da",
          "error": "#8250df", "superseded": "#8c959f"}
CSS = """
:root{--bg:#fff;--fg:#1f2328;--mut:#656d76;--bd:#d0d7de;--card:#f6f8fa}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--bd:#30363d;--card:#161b22}}
*{box-sizing:border-box}body{font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:1150px;margin:0 auto;padding:20px}
a{color:#0969da;text-decoration:none}a:hover{text-decoration:underline}h1{font-size:20px;margin:0 0 4px}.m{color:var(--mut)}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;color:#fff;font-size:12px;font-weight:600;white-space:nowrap}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:10px 14px}.card b{font-size:22px;display:block}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--bd);padding:7px 8px;text-align:left;vertical-align:top}th{color:var(--mut);font-weight:500}
form{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:12px;margin:14px 0;display:flex;gap:8px;flex-wrap:wrap;align-items:end}
label{font-size:12px;color:var(--mut);display:block}input{padding:5px 8px;border:1px solid var(--bd);border-radius:6px;background:var(--bg);color:var(--fg)}
button{padding:6px 14px;border:0;border-radius:6px;background:#1f6feb;color:#fff;cursor:pointer}
iframe{width:100%;height:900px;border:1px solid var(--bd);border-radius:8px;background:#fff}code{font:12px ui-monospace,monospace}
"""
CSP = ("default-src 'none'; style-src 'unsafe-inline'; frame-src 'self'; form-action 'self'; img-src data:; "
       "base-uri 'none'; frame-ancestors 'self'")
e = html.escape


def _badge(label: str | None) -> str:
    label = label or "-"
    return f"<span class=badge style='background:{COLORS.get(label, '#656d76')}'>{e(label)}</span>"


def _t(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "-"


def _ref(r: dict) -> str:
    if r.get("pr_number") is not None:
        return f"PR #{int(r['pr_number'])}"
    return f"{r.get('base') or '?'} … {r.get('head') or 'HEAD'}"


def page(title: str, body: str, refresh: bool = False) -> str:
    meta = "<meta http-equiv=refresh content=5>" if refresh else ""
    return (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>{meta}"
            f"<title>{e(title)}</title><style>{CSS}</style><body>{body}</body></html>")


def dashboard(stats: dict, runs: list, csrf: str, allow_local: bool, version: str, filters: dict) -> str:
    cards = "".join(f"<div class=card><span class=m>{e(k)}</span><b>{stats.get(k, 0)}</b></div>"
                    for k in ("total", "PASS", "BLOCK", "REVIEW_REQUIRED", "queued", "running", "error"))
    form = ""
    if allow_local:
        form = (f"<form method=post action=/ui/verify><input type=hidden name=csrf value='{e(csrf)}'>"
                "<div><label>Local repository path</label><input name=repo_path size=44 required></div>"
                "<div><label>Base</label><input name=base value=main size=12></div>"
                "<div><label>Head</label><input name=head value=HEAD size=18></div>"
                "<div><button>Verify</button></div></form>")
    rows = "".join(
        f"<tr><td class=m>{_t(r['created'])}</td><td>{e(r['repo'])}<br><span class=m>{e(_ref(r))}</span></td>"
        f"<td>{_badge(r['verdict'] if r['status'] == 'done' else r['status'])}</td>"
        f"<td>{e((r.get('summary') or r.get('error') or '')[:160])}</td>"
        f"<td><a href='/runs/{e(r['id'])}'>open</a></td></tr>" for r in runs) or "<tr><td colspan=5 class=m>No runs yet.</td></tr>"
    active = stats.get("queued", 0) + stats.get("running", 0) > 0
    body = (f"<h1>RepoShield</h1><div class=m>deterministic verification of AI-generated changes · v{e(version)}</div>"
            f"<div class=cards>{cards}</div>{form}"
            f"<table><tr><th>When</th><th>Repository</th><th>Verdict</th><th>Why</th><th></th></tr>{rows}</table>")
    return page("RepoShield", body, refresh=active)


def run_page(row: dict, result: dict | None, chain: tuple[bool, str] | None) -> str:
    status = row["verdict"] if row["status"] == "done" else row["status"]
    facts = ""
    if result:
        fp, p, t = result["fingerprint"], result["plan"], result["tests"]
        tests = (f"{p['selected']}/{p['total']} test files ({p['reduction_pct']}% fewer), {t.get('passed', 0)} passed, "
                 f"{t.get('failed', 0)} failed" if t["status"] == "RAN" else f"{t['status']}: {t.get('reason', '')}")
        facts = ("<table>" + "".join(f"<tr><th>{e(k)}</th><td>{v}</td></tr>" for k, v in [
            ("Head", f"<code>{e(fp['head'][:12])}</code>"), ("Base", f"<code>{e(fp['base'][:12])}</code>"),
            ("Policy", f"<code>{e(fp['policy_hash'][:12])}</code> from {e(fp['policy_source'])}"),
            ("Sandbox", e(fp["sandbox"])), ("Tests", e(tests)),
            ("Graph", f"{result['graph']['files']} files, re-parsed {result['graph']['reparsed']}"),
            ("Impact", f"{result['impact_total']} file(s) potentially affected")]) + "</table>")
    chain_html = ""
    if chain:
        ok, msg = chain
        chain_html = f"<p>Audit chain: <b style='color:{'#1a7f37' if ok else '#cf222e'}'>{'intact' if ok else 'TAMPERED'}</b> <span class=m>{e(msg)}</span></p>"
    frame = f"<iframe sandbox src='/api/v1/runs/{e(row['id'])}/report' title=report></iframe>" if result else ""
    err = f"<p style='color:#cf222e'>{e(row['error'])}</p>" if row.get("error") else ""
    body = (f"<p><a href=/>← all runs</a></p><h1>{e(row['repo'])} · {e(_ref(row))} {_badge(status)}</h1>"
            f"<p>{e(row.get('summary') or '')}</p>{err}{facts}{chain_html}{frame}")
    return page(f"RepoShield {row['id']}", body, refresh=row["status"] in ("queued", "running"))
