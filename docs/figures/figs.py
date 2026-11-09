import resvg_py, html
F = "DejaVu Sans, Arial, sans-serif"
C = {"navy": "#0b2447", "blue": "#1f6feb", "lblue": "#ddf4ff", "grey": "#f6f8fa", "line": "#9aa5b1", "green": "#1a7f37", "lgreen": "#dafbe1",
     "red": "#cf222e", "lred": "#ffebe9", "amber": "#9a6700", "lamber": "#fff8c5", "purple": "#6f42c1", "lpurple": "#f3ecff", "ink": "#1f2328", "mut": "#57606a"}
e = html.escape

class S:
    def __init__(self, w, h):
        self.w, self.h, self.p = w, h, []
        self.p.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="{F}">'
                      '<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#57606a"/></marker>'
                      '<marker id="ab" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#1f6feb"/></marker></defs>'
                      f'<rect width="{w}" height="{h}" fill="#fff"/>')
    def box(self, x, y, w, h, title, sub="", fill="#f6f8fa", stroke="#9aa5b1", tc="#1f2328", ts=12, r=7, sw=1.4, dash=False):
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"' + (' stroke-dasharray="5 4"' if dash else '') + '/>')
        if sub:
            self.p.append(f'<text x="{x + w / 2}" y="{y + h / 2 - 3}" text-anchor="middle" font-size="{ts}" font-weight="700" fill="{tc}">{e(title)}</text>')
            for i, line in enumerate(sub.split("\n")):
                self.p.append(f'<text x="{x + w / 2}" y="{y + h / 2 + 11 + i * 11.5}" text-anchor="middle" font-size="9.6" fill="{C["mut"]}">{e(line)}</text>')
        else:
            self.p.append(f'<text x="{x + w / 2}" y="{y + h / 2 + 4}" text-anchor="middle" font-size="{ts}" font-weight="700" fill="{tc}">{e(title)}</text>')
    def label(self, x, y, t, size=11, color="#57606a", bold=True, anchor="start"):
        self.p.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}" text-anchor="{anchor}" letter-spacing=".4">{e(t)}</text>')
    def group(self, x, y, w, h, title, stroke="#1f6feb", fill="#fbfdff"):
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
        self.label(x + 10, y + 15, title, 10.5, stroke)
    def arrow(self, x1, y1, x2, y2, blue=False, dash=False):
        self.p.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{"#1f6feb" if blue else "#57606a"}" stroke-width="1.8" marker-end="url(#{"ab" if blue else "a"})"' + (' stroke-dasharray="5 4"' if dash else '') + '/>')
    def png(self, path, zoom=2.0):
        svg = "".join(self.p) + "</svg>"
        open(path.replace(".png", ".svg"), "w").write(svg)
        open(path, "wb").write(bytes(resvg_py.svg_to_bytes(svg_string=svg, zoom=zoom, background="white")))

# ---------------------------------------------------------------- Fig 1: system architecture
s = S(860, 492)
s.label(8, 14, "INPUT", 10.5)
s.box(8, 26, 108, 62, "AI coding agent", "or developer\nopens a pull request", C["lpurple"], C["purple"])
s.box(8, 118, 108, 62, "Git repository", "base branch + head\n(PR commit)", C["grey"])
s.arrow(62, 88, 62, 118)
s.arrow(116, 148, 142, 148, blue=True)
s.group(142, 4, 520, 486, "REPOSHIELD  (Python 3.10+)")
# interfaces
s.label(154, 38, "Interfaces", 10, C["mut"])
for i, (t, sub) in enumerate([("CLI", "reposhield verify"), ("REST API", "FastAPI"), ("Webhook", "HMAC-SHA256"), ("Dashboard", "HTML + CSP")]):
    s.box(154 + i * 127, 44, 118, 40, t, sub, C["lblue"], C["blue"])
s.box(154, 96, 496, 26, "Job queue + workers (SQLite)  -  idempotent, restart-safe", "", C["grey"])
s.arrow(402, 84, 402, 96)
# engine
s.group(154, 134, 496, 182, "VERIFICATION ENGINE  -  deterministic, no LLM", "#0b2447", "#f8faff")
mods = [("Git layer", "merge-base, diff,\ncommit tree"), ("Python analyzer", "AST: imports, defs,\ntests, dynamic imports"), ("Dependency graph", "incremental +\nreverse reachability"),
        ("Policy engine", ".reposhield.yml\nread from BASE branch"), ("Built-in checks", "secrets, test integrity,\ndependencies, syntax"), ("Test selector", "static + coverage;\nunsure = run all")]
for i, (t, sub) in enumerate(mods):
    s.box(164 + (i % 3) * 160, 152 + (i // 3) * 62, 152, 54, t, sub, "#fff", "#8c959f", ts=11.5)
s.box(164, 278, 476, 30, "Verdict aggregator:  any BLOCK  >  any REVIEW / UNKNOWN  >  PASS", "", C["lamber"], C["amber"], ts=11)
s.arrow(402, 122, 402, 134)
# sandbox
s.arrow(402, 316, 402, 330)
s.group(154, 330, 496, 80, "SANDBOX  -  untrusted repository code runs only here", C["red"], "#fffafa")
s.box(164, 348, 296, 54, "Docker backend", "no network, read-only FS, non-root,\nCPU / memory / PID limits, timeout", C["lred"], C["red"])
s.box(470, 348, 170, 54, "Dev backend", "rlimits, scrubbed env", "#fff", "#8c959f")
# evidence
s.group(154, 420, 496, 68, "EVIDENCE AND CONTROL", C["green"], "#fbfffc")
s.box(164, 438, 148, 42, "Audit hash-chain", "tamper-evident log", C["lgreen"], C["green"])
s.box(320, 438, 148, 42, "Reports", "HTML / Markdown / JSON", C["lgreen"], C["green"])
s.box(476, 438, 164, 42, "Action gateway", "signed, single-use tokens", C["lgreen"], C["green"])
# outputs
s.arrow(662, 148, 690, 148, blue=True)
s.label(698, 14, "OUTPUT", 10.5)
for i, (t, sub, f, st) in enumerate([("GitHub", "commit status +\nPR comment", C["lblue"], C["blue"]), ("Dashboard", "verdicts, evidence,\naudit-chain check", C["lblue"], C["blue"]),
                                     ("CI exit code", "0 PASS | 1 BLOCK |\n2 REVIEW | 3 error", C["lblue"], C["blue"]), ("Verdict", "PASS / REVIEW_REQUIRED\n/ BLOCK + evidence", C["lamber"], C["amber"])]):
    s.box(698, 26 + i * 84, 154, 64, t, sub, f, st)
s.png("fig1_architecture.png")

# ---------------------------------------------------------------- Fig 2: pipeline
p = S(860, 238)
steps = [("1  Diff", "changed files and\nadded lines vs\nmerge-base"), ("2  Graph", "AST import graph,\nupdated\nincrementally"), ("3  Impact", "who depends on\nthe change\n(reverse BFS)"),
         ("4  Rules", "policy from base,\nsecrets, test\nintegrity"), ("5  Select", "tests reached by\nthe change; else\nfull suite"), ("6  Sandbox", "run selected\ntests in an\nisolated box"), ("7  Verdict", "aggregate +\nwrite hash-\nchained audit")]
for i, (t, sub) in enumerate(steps):
    x = 6 + i * 122
    p.box(x, 8, 112, 102, t, sub, C["lblue"] if i < 6 else C["lamber"], C["blue"] if i < 6 else C["amber"], ts=12.5)
    if i < 6:
        p.arrow(x + 112, 59, x + 122, 59, blue=True)
p.label(8, 134, "DECISION RULE  (fixed, auditable - never a score, never an LLM)", 10.5)
p.box(8, 144, 268, 84, "PASS", "no rule violated and every\nselected test passed", C["lgreen"], C["green"], C["green"], ts=15)
p.box(296, 144, 268, 84, "REVIEW_REQUIRED", "evidence missing or uncertain\n(unknown is never a pass)", C["lamber"], C["amber"], C["amber"], ts=15)
p.box(584, 144, 268, 84, "BLOCK", "critical or high rule broken,\nor a required test fails", C["lred"], C["red"], C["red"], ts=15)
p.png("fig2_pipeline.png")
print("figures ok")

# ---------------------------------------------------------------- Fig 4: results (measured, benchmark/bench.py)
c = S(860, 236)
c.label(8, 16, "(a) Test files run per change - average over 12 seeded bugs (9 files in suite)", 11, C["ink"])
rows = [("Full suite", 9.0, "12 / 12 bugs caught", "#8c959f"), ("Filename heuristic", 0.9, "10 / 12 caught  (misses 2)", C["red"]), ("RepoShield (dependency graph)", 2.8, "12 / 12 bugs caught", C["green"])]
for i, (name, v, note, col) in enumerate(rows):
    y = 34 + i * 44
    c.p.append(f'<text x="8" y="{y + 19}" font-size="11.5" fill="{C["ink"]}">{name}</text>')
    c.p.append(f'<rect x="200" y="{y + 4}" width="{max(v, .35) * 30:.0f}" height="22" rx="4" fill="{col}"/>')
    c.p.append(f'<text x="{208 + v * 30:.0f}" y="{y + 20}" font-size="11.5" font-weight="700" fill="{C["ink"]}">{v}</text>')
    c.p.append(f'<text x="{250 + v * 30 + 20:.0f}" y="{y + 20}" font-size="10.5" fill="{col if col != "#8c959f" else C["mut"]}">{note}</text>')
c.label(8, 182, "(b) Dependency-graph update - 2,000 Python files, 5 changed", 11, C["ink"])
for i, (name, v, col, txt) in enumerate([("Full rebuild", 0.912, "#8c959f", "0.912 s"), ("Incremental", 0.071, C["blue"], "0.071 s   (12.8x faster, identical graph)")]):
    y = 190 + i * 22
    c.p.append(f'<text x="8" y="{y + 13}" font-size="11.5" fill="{C["ink"]}">{name}</text>')
    c.p.append(f'<rect x="200" y="{y}" width="{v * 330:.0f}" height="16" rx="3" fill="{col}"/>')
    c.p.append(f'<text x="{208 + v * 330:.0f}" y="{y + 13}" font-size="11" font-weight="700" fill="{C["ink"]}">{txt}</text>')
c.png("fig4_results.png")
print("fig4 ok")
