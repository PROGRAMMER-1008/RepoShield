from __future__ import annotations

import html
import time

ICON = {"PASS": "✅", "BLOCK": "❌", "REVIEW_REQUIRED": "⚠️"}
EFFECT_ICON = {"BLOCK": "❌", "REVIEW": "⚠️", "INFO": "ℹ️", "NONE": "✅"}


def _loc(ev: dict) -> str:
    if "file" in ev and "line" in ev:
        return f"{ev['file']}:{ev['line']}"
    return ev.get("file") or ev.get("test") or ""


SVG_STYLE = """<style>
.bx{fill:#f6f8fa;stroke:#d0d7de;stroke-width:1.5}.bx.ch{fill:#fff8c5;stroke:#bf8700;stroke-width:2.5}
.bx.vi{fill:#ffebe9;stroke:#cf222e;stroke-width:2.5}.bx.ts{fill:#ddf4ff;stroke:#0969da;stroke-width:2}.tag{fill:#bf8700}.tagt{font:700 9px system-ui,sans-serif;fill:#fff}.bdg{fill:#0969da}.bdgt{font:600 10px system-ui,sans-serif;fill:#fff}
.t1{font:600 12.5px system-ui,sans-serif;fill:#1f2328}.t2{font:10.5px system-ui,sans-serif;fill:#656d76}.lg{font:11px system-ui,sans-serif;fill:#656d76}
.e{fill:none;stroke:#8c959f;stroke-width:1.6}.e.vi{stroke:#cf222e;stroke-width:3}.ah{fill:#8c959f}.ahv{fill:#cf222e}
@media(prefers-color-scheme:dark){.bx{fill:#161b22;stroke:#30363d}.bx.ch{fill:#3d2e00;stroke:#d29922}.bx.vi{fill:#3c1618;stroke:#f85149}
.tag{fill:#9e6a03}.bdg{fill:#1f6feb}.t1{fill:#e6edf3}.t2,.lg{fill:#8b949e}.e{stroke:#6e7681}.ah{fill:#6e7681}}
</style>"""


def _short(path: str, n: int) -> str:
    return path if len(path) <= n else "…" + path[-(n - 1):]


def _is_test(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return base.startswith("test_") or base.endswith("_test.py")


def graph_svg(r: dict, max_nodes: int = 16) -> str:
    """Impact map: arrows point from importer to imported. Red = dependency path that breaks a rule, amber tag = changed file,
    blue badge = test files that exercise a file. Pure SVG (no JS) so it works in reports, e-mail and PDFs."""
    changed = {c["path"] for c in r["changes"] if c["path"].endswith(".py")}
    viol = [ev["path"] for f in r["findings"] if f["effect"] in ("BLOCK", "REVIEW") for ev in f["evidence"]
            if isinstance(ev.get("path"), list) and len(ev["path"]) >= 2 and ev["path"][-1].endswith(".py")]
    edges: dict[tuple, str] = {}
    prio: dict[str, int] = {}
    for path in viol:
        for a, b in zip(path, path[1:]):
            edges[(a, b)] = "vi"
        for n in path:
            prio[n] = 0
    for c in changed:
        prio.setdefault(c, 1)
    for i in r["impact"]:
        via = i["via"]
        for k in range(len(via) - 1):
            edges.setdefault((via[k + 1], via[k]), "")
            prio.setdefault(via[k], 1 if via[k] in changed else 2 + i["distance"])
            prio.setdefault(via[k + 1], 2 + i["distance"])
    badge: dict[str, int] = {}
    for (a, b) in edges:
        if _is_test(a) and not _is_test(b):
            badge[b] = badge.get(b, 0) + 1
    keep = sorted((n for n in prio if not _is_test(n)), key=lambda n: (prio[n], n))
    hidden = max(0, len(keep) - max_nodes)
    keep = keep[:max_nodes]
    kset = set(keep)
    edges = {e_: k for e_, k in edges.items() if e_[0] in kset and e_[1] in kset}
    if len(keep) < 2:
        return ""
    rank = {n: 0 for n in keep}
    for _ in range(len(keep)):
        moved = False
        for (a, b) in edges:
            if rank[b] < rank[a] + 1 < len(keep):
                rank[b], moved = rank[a] + 1, True
        if not moved:
            break
    vnodes = {n for path in viol for n in path}
    cols: dict[int, list] = {}
    for n in sorted(keep, key=lambda x: (prio[x], x)):
        cols.setdefault(rank[n], []).append(n)
    W, H, CW, RH, PAD, TOP = 200, 46, 262, 70, 22, 16
    ncol, nrow = len(cols), max(len(v) for v in cols.values())
    width, height = max(PAD * 2 + (ncol - 1) * CW + W, 840), TOP + PAD + (nrow - 1) * RH + H + 40
    pos = {}
    xoff = (width - (PAD * 2 + (ncol - 1) * CW + W)) / 2
    for c, members in cols.items():
        top = TOP + PAD + ((nrow - len(members)) * RH) / 2
        for k, n in enumerate(members):
            pos[n] = (PAD + xoff + c * CW, top + k * RH)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
           f'aria-label="dependency impact map" style="max-width:100%;height:auto">', SVG_STYLE,
           '<defs><marker id="ar" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" refX="10" refY="5.5" orient="auto"><path d="M0,0 L11,5.5 L0,11 z" class="ah"/></marker>'
           '<marker id="arv" markerUnits="userSpaceOnUse" markerWidth="13" markerHeight="13" refX="12" refY="6.5" orient="auto"><path d="M0,0 L13,6.5 L0,13 z" class="ahv"/></marker></defs>']
    for (a, b), kind in sorted(edges.items(), key=lambda kv: kv[1] == "vi"):
        (x1, y1), (x2, y2) = pos[a], pos[b]
        x1, y1, x2, y2 = x1 + W, y1 + H / 2, x2 - 3, y2 + H / 2
        out.append(f'<path class="e{" vi" if kind == "vi" else ""}" d="M{x1:.0f},{y1:.0f} C{x1 + 50:.0f},{y1:.0f} {x2 - 50:.0f},{y2:.0f} {x2:.0f},{y2:.0f}" '
                   f'marker-end="url(#{"arv" if kind == "vi" else "ar"})"/>')
    for n, (x, y) in pos.items():
        cls = "vi" if n in vnodes else ("ch" if n in changed else "n")
        d, _, f = n.rpartition("/")
        out.append(f'<g><title>{html.escape(n)}</title><rect class="bx {cls}" x="{x:.0f}" y="{y:.0f}" width="{W}" height="{H}" rx="8"/>'
                   f'<text class="t1" x="{x + 10:.0f}" y="{y + 19:.0f}">{html.escape(_short(f, 25))}</text>'
                   f'<text class="t2" x="{x + 10:.0f}" y="{y + 35:.0f}">{html.escape(_short(d + "/" if d else "./", 30))}</text>')
        if n in changed:
            out.append(f'<rect class="tag" x="{x + 8:.0f}" y="{y - 9:.0f}" width="58" height="16" rx="8"/>'
                       f'<text class="tagt" x="{x + 37:.0f}" y="{y + 3:.0f}" text-anchor="middle">CHANGED</text>')
        if badge.get(n):
            k = badge[n]
            lab = f"{k} test{'s' if k > 1 else ''}"
            bw = 12 + 6.4 * len(lab)
            out.append(f'<rect class="bdg" x="{x + W - bw - 6:.0f}" y="{y + H - 9:.0f}" width="{bw:.0f}" height="16" rx="8"/>'
                       f'<text class="bdgt" x="{x + W - bw / 2 - 6:.0f}" y="{y + H + 3:.0f}" text-anchor="middle">{lab}</text>')
        out.append("</g>")
    if hidden:
        height += 18
        out[0] = out[0].replace(f'viewBox="0 0 {width} {height - 18}"', f'viewBox="0 0 {width} {height}"').replace(f'height="{height - 18}"', f'height="{height}"')
    ly = height - 12 - (18 if hidden else 0)
    for i, (cls, label) in enumerate([("ch", "changed file"), ("vi", "breaks a rule"), ("n", "affected, unchanged"), ("bdg", "test files that cover it")]):
        lx = PAD + i * 200
        out.append(f'<rect class="{"bx " if cls != "bdg" else ""}{cls}" x="{lx}" y="{ly - 10}" width="14" height="11" rx="3"/>'
                   f'<text class="lg" x="{lx + 20}" y="{ly}">{label}</text>')
    if hidden:
        out.append(f'<text class="lg" x="{PAD}" y="{height - 5}">+{hidden} more affected file(s) not drawn - see the full list in the report</text>')
    out.append("</svg>")
    return "".join(out)


MEANING = {
    "PASS": "Nothing in this change violates a rule, and every test that could be affected passed. Safe to merge from RepoShield's point of view.",
    "BLOCK": "Do not merge. At least one mandatory rule is violated or a required test fails. The evidence below shows exactly where.",
    "REVIEW_REQUIRED": "RepoShield cannot prove this change is safe. A human must look at the items below before it can merge.",
}


def tiles(r: dict) -> list[tuple[str, str, str]]:
    p, t = r["plan"], r["tests"]
    blocking = sum(1 for f in r["findings"] if f["effect"] == "BLOCK")
    review = sum(1 for f in r["findings"] if f["effect"] == "REVIEW")
    tests = (f"{p['selected']} of {p['total']}" if t["status"] == "RAN" else t["status"].replace("_", " ").lower())
    reason = t.get("reason") or ""
    sub = (f"{p['reduction_pct']}% fewer than the full suite" if t["status"] == "RAN"
           else "change already blocked - tests skipped" if reason.startswith("skipped: a blocking") else reason[:56] + ("…" if len(reason) > 56 else ""))
    nf, ni = len(r["changes"]), r["impact_total"]
    return [(str(nf), "file changed" if nf == 1 else "files changed", f"{sum(c['added'] for c in r['changes'])} lines added, {sum(c['deleted'] for c in r['changes'])} removed"),
            (str(ni), "file potentially affected" if ni == 1 else "files potentially affected", "found by tracing who imports the change"),
            (tests, "test files run", sub),
            (f"{blocking} / {review}", "blocking / review findings", "from policy, secrets, tests, integrity")]


def markdown(r: dict) -> str:
    p, t = r["plan"], r["tests"]
    L = [f"## RepoShield — {ICON[r['verdict']]} {r['verdict']}", "", f"**{r['summary']}**", ""]
    L += [f"Mode: {r.get('mode', 'VERIFICATION ONLY')} · Execution: {r.get('execution_state', 'unknown-outcome')}", ""]
    bad = [f for f in r["findings"] if f["effect"] in ("BLOCK", "REVIEW")]
    if bad:
        L += ["### Findings", ""]
        for f in bad:
            L.append(f"- {EFFECT_ICON[f['effect']]} **{f['rule_id']}** ({f['severity']}) — {f['message']}")
            for ev in f["evidence"][:5]:
                if "path" in ev and isinstance(ev["path"], list):
                    L.append(f"  - `{_loc(ev)}` via `{' → '.join(ev['path'])}`")
                elif _loc(ev):
                    L.append(f"  - `{_loc(ev)}`" + (f" — {ev['issue']}" if "issue" in ev else ""))
        L.append("")
    L += ["### Tests", ""]
    if t["status"] == "RAN":
        L.append(f"- Selected **{p['selected']} of {p['total']}** test files ({p['reduction_pct']}% fewer) · mode `{p['mode']}`"
                 f" · {t['executed']} tests: {t['passed']} passed, {t['failed']} failed, {t['skipped']} skipped · {t['duration_ms']} ms")
    else:
        L.append(f"- {t['status'].replace('_', ' ').title()}: {t.get('reason', '')}")
    for fr in p["fallback_reasons"][:3]:
        L.append(f"- Full-suite fallback: {fr}")
    L += ["", "### Impact", "",
          f"- {r['impact_total']} file(s) *potentially affected* (reverse dependency reachability — not proof of breakage)", "",
          "### Provenance", "",
          f"- run `{r['run_id']}` · head `{r['fingerprint']['head'][:10]}` · base `{r['fingerprint']['base'][:10]}`"
          f" · policy `{r['fingerprint']['policy_hash'][:10]}` from `{r['fingerprint']['policy_source']}`"
          f" · sandbox `{r['fingerprint']['sandbox']}` · audit head `{r['audit']['head_hash'][:12]}`", ""]
    return "\n".join(L)


def html_report(r: dict, events: list) -> str:
    e = html.escape
    color = {"PASS": "#1a7f37", "BLOCK": "#cf222e", "REVIEW_REQUIRED": "#bf8700"}[r["verdict"]]
    rows = ""
    for f in r["findings"]:
        if f["result"] in ("NOT_APPLICABLE",):
            continue
        ev = "".join(f"<div class=ev>{e(_loc(x) or '')} {e(' → '.join(x['path']) if isinstance(x.get('path'), list) else x.get('issue', ''))}</div>"
                     for x in f["evidence"][:6] if _loc(x) or x.get("issue") or x.get("path"))
        rows += (f"<tr><td>{EFFECT_ICON[f['effect']]}</td><td><b>{e(f['rule_id'])}</b><br><small>{e(f['rule_type'])}</small></td>"
                 f"<td>{e(f['severity'])}</td><td>{e(f['result'])}</td><td>{e(f['message'])}{ev}</td></tr>")
    tests = "".join(f"<tr><td>{e(t['path'])}</td><td>{t['confidence']}</td><td>{e('; '.join(x.get('kind', '') + (' ← ' + x['changed'] if 'changed' in x else '') for x in t['reasons'][:2]))}</td></tr>"
                    for t in r["plan"]["tests"][:60])
    imp = "".join(f"<tr><td>{e(i['file'])}</td><td>{i['distance']}</td><td>{e(' → '.join(i['via']))}</td></tr>" for i in r["impact"][:60])
    ev_rows = "".join(f"<tr><td>{x['seq']}</td><td>{time.strftime('%H:%M:%S', time.localtime(x['ts']))}</td><td>{e(x['type'])}</td><td>{e(x['actor'])}</td><td><code>{x['hash'][:12]}</code></td></tr>" for x in events)
    fp = r["fingerprint"]
    svg = graph_svg(r)
    map_block = (f"<h2>Impact map <small>who depends on whom — arrows point from importer to imported</small></h2><div class=map>{svg}</div>"
                 if svg else "")
    chg = "".join(f"<tr><td><code>{e(c['status'])}</code></td><td>{e(c['path'])}</td><td class=m>+{c['added']} −{c['deleted']}</td></tr>" for c in r["changes"][:40])
    map_block += f"<h2>What changed <small>{len(r['changes'])} file(s)</small></h2><table><tr><th></th><th>File</th><th>Lines</th></tr>{chg}</table>" if chg else ""
    return f"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>RepoShield {e(r['run_id'])}</title><style>
:root{{--bg:#fff;--fg:#1f2328;--mut:#656d76;--bd:#d0d7de;--card:#f6f8fa}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--bd:#30363d;--card:#161b22}}}}
body{{font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:1000px;margin:0 auto;padding:24px}}
h1{{font-size:20px}} .v{{display:inline-block;padding:4px 12px;border-radius:6px;color:#fff;background:{color};font-weight:600}}
table{{border-collapse:collapse;width:100%;margin:8px 0 24px}} td,th{{border-bottom:1px solid var(--bd);padding:6px 8px;text-align:left;vertical-align:top}}
th{{color:var(--mut);font-weight:500}} .ev{{font:12px ui-monospace,monospace;color:var(--mut)}} small,.m{{color:var(--mut)}}
code{{font:12px ui-monospace,monospace}} .mean{{background:var(--card);border-left:4px solid {color};padding:10px 14px;border-radius:6px;margin:12px 0}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:14px 0}}
.tile{{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:10px 14px}}.tile b{{font-size:24px;display:block}}.tile span{{display:block}}.tile small{{color:var(--mut)}}
.map{{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:10px;overflow-x:auto}}
details{{background:var(--card);border:1px solid var(--bd);border-radius:6px;padding:8px 12px;margin:8px 0}}
</style><body>
<h1>RepoShield · {e(r['project'])} <span class=v>{r['verdict']}</span></h1>
<p>{e(r.get('mode', 'VERIFICATION ONLY'))} · Execution: {e(r.get('execution_state', 'unknown-outcome'))}</p>
<p>{e(r['summary'])}</p>
<p class=m>run <code>{e(r['run_id'])}</code> · head <code>{fp['head'][:10]}</code> · base <code>{fp['base'][:10]}</code> · policy <code>{fp['policy_hash'][:10]}</code> ({e(fp['policy_source'])}) · sandbox {e(fp['sandbox'])} · {r['timings_ms']['total']} ms</p>
<div class=mean>{e(MEANING[r['verdict']])}</div>
<div class=tiles>{"".join(f"<div class=tile><b>{e(a)}</b><span>{e(b)}</span><small>{e(c)}</small></div>" for a, b, c in tiles(r))}</div>
{map_block}
<h2>Findings</h2><table><tr><th></th><th>Rule</th><th>Severity</th><th>Result</th><th>Evidence</th></tr>{rows}</table>
<h2>Test plan <small>{r['plan']['mode']} · {r['plan']['selected']}/{r['plan']['total']} files · {r['plan']['reduction_pct']}% fewer</small></h2>
<table><tr><th>Test file</th><th>Confidence</th><th>Why selected</th></tr>{tests}</table>
<h2>Potential impact <small>{r['impact_total']} files</small></h2>
<table><tr><th>File</th><th>Distance</th><th>Dependency path</th></tr>{imp}</table>
<details><summary>Audit chain ({len(events)} events, head <code>{r['audit']['head_hash'][:12]}</code>)</summary>
<table><tr><th>#</th><th>Time</th><th>Event</th><th>Actor</th><th>Hash</th></tr>{ev_rows}</table></details>
</body></html>"""


# ------------------------------------------------------------------ demo gallery (for presentations)
def gallery_html(rows: list, version: str) -> str:
    """rows: [{branch, story, expected, result(dict from verify), report_uri}] -> one self-contained page."""
    e = html.escape
    col = {"PASS": "#1a7f37", "BLOCK": "#cf222e", "REVIEW_REQUIRED": "#bf8700"}
    icon = {"PASS": "✓", "BLOCK": "✕", "REVIEW_REQUIRED": "!"}
    n = len(rows)
    cnt = {v: sum(1 for x in rows if x["result"]["verdict"] == v) for v in col}
    ran = [x["result"] for x in rows if x["result"]["tests"]["status"] == "RAN"]
    sel, tot = sum(r["plan"]["selected"] for r in ran), sum(r["plan"]["total"] for r in ran)
    saved = f"{round(100 * (1 - sel / tot))}%" if tot else "–"
    match = sum(1 for x in rows if x["expected"] in ("-", x["result"]["verdict"]))
    flow = "".join(f"<div class=st><b>{a}</b><span>{b}</span></div>" + ("<i>→</i>" if k < 4 else "")
                   for k, (a, b) in enumerate([("1 · Diff", "what exactly changed"), ("2 · Graph", "who depends on it"),
                                               ("3 · Rules", "policy, secrets, tests"), ("4 · Sandbox", "run only needed tests"),
                                               ("5 · Verdict", "PASS · REVIEW · BLOCK")]))
    cards = ""
    for x in rows:
        r = x["result"]; v = r["verdict"]; t = r["tests"]; p = r["plan"]
        ran_txt = f"{p['selected']} of {p['total']} test files ran" if t["status"] == "RAN" else {"NOT_RUN": "tests skipped – already blocked", "NOT_NEEDED": "no tests needed"}.get(t["status"], t["status"].lower())
        cards += (f"<a class=card style='border-top-color:{col[v]}' href='{e(x['report_uri'])}'>"
                  f"<div class=top><code>{e(x['branch'])}</code><span class=bd style='background:{col[v]}'>{icon[v]} {e(v.replace('_', ' '))}</span></div>"
                  f"<p class=story><small>THE AI AGENT…</small>{e(x['story'])}</p>"
                  f"<p class=why><small>REPOSHIELD FOUND</small>{e(r['summary'][:170])}</p>"
                  f"<div class=foot><span>{e(ran_txt)}</span><span>{r['timings_ms']['total'] / 1000:.1f}s</span><span class=go>open evidence →</span></div></a>")
    return f"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>RepoShield · demo gallery</title><style>
:root{{--bg:#f6f8fa;--fg:#1f2328;--mut:#656d76;--bd:#d0d7de;--card:#fff}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--bd:#30363d;--card:#161b22}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
.hero{{background:linear-gradient(135deg,#0b2447,#19376d 55%,#576cbc);color:#fff;padding:38px 24px 30px}}
.wrap{{max-width:1180px;margin:0 auto}}h1{{margin:0;font-size:30px;letter-spacing:-.5px}}.hero p{{margin:6px 0 0;opacity:.85;max-width:760px}}
.flow{{display:flex;align-items:center;gap:8px;margin:22px 0 4px;flex-wrap:wrap}}.st{{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.25);border-radius:10px;padding:8px 14px}}
.st b{{display:block;font-size:14px}}.st span{{font-size:12px;opacity:.8}}.flow i{{opacity:.6;font-style:normal}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:-26px auto 18px;max-width:1180px;padding:0 24px}}
.k{{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:12px 16px;box-shadow:0 4px 14px rgba(0,0,0,.08)}}.k b{{font-size:30px;line-height:1;display:block}}.k span{{color:var(--mut);font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(350px,1fr));gap:16px;padding:0 24px 40px;max-width:1180px;margin:0 auto}}
.card{{background:var(--card);border:1px solid var(--bd);border-top:5px solid;border-radius:12px;padding:14px 16px;color:inherit;text-decoration:none;display:flex;flex-direction:column;transition:transform .12s,box-shadow .12s}}
.card:hover{{transform:translateY(-3px);box-shadow:0 8px 22px rgba(0,0,0,.14)}}.top{{display:flex;justify-content:space-between;gap:8px;align-items:center}}
.bd{{color:#fff;font-size:12px;font-weight:700;padding:2px 10px;border-radius:12px;white-space:nowrap}}code{{font:13px ui-monospace,monospace;font-weight:600}}
p{{margin:10px 0 0}}small{{display:block;color:var(--mut);font-size:10.5px;letter-spacing:.8px;font-weight:600}}.why{{font-weight:500}}
.foot{{margin-top:auto;padding-top:12px;display:flex;gap:12px;color:var(--mut);font-size:12.5px}}.go{{margin-left:auto;color:#0969da;font-weight:600}}
footer{{text-align:center;color:var(--mut);font-size:12px;padding:0 0 30px}}
</style><body><div class=hero><div class=wrap><h1>RepoShield</h1>
<p>AI agents now open pull requests faster than people can review them. RepoShield checks every change <b>deterministically</b> — what it touches, which rules it breaks, which tests matter — and answers with evidence, not opinions.</p>
<div class=flow>{flow}</div></div></div>
<div class=kpis><div class=k><b>{n}</b><span>AI-agent pull requests checked</span></div>
<div class=k><b style="color:{col['BLOCK']}">{cnt['BLOCK']}</b><span>blocked before merge</span></div>
<div class=k><b style="color:{col['REVIEW_REQUIRED']}">{cnt['REVIEW_REQUIRED']}</b><span>sent to a human</span></div>
<div class=k><b style="color:{col['PASS']}">{cnt['PASS']}</b><span>safe to merge</span></div>
<div class=k><b>{saved}</b><span>fewer test files run ({sel} of {tot})</span></div>
<div class=k><b>{match}/{n}</b><span>verdicts as designed</span></div></div>
<div class=grid>{cards}</div><footer>RepoShield v{e(version)} · click any card for the full evidence report (impact map, findings, audit chain)</footer></body></html>"""
