# Roadmap (what comes after this prototype)

Phase 1 – done in this repo: deterministic core, CLI, policy engine, incremental graph, selective tests, sandbox backends,
audit chain, action gateway, GitHub Action workflow, demo + benchmarks.

Phase 2 – make it a service  **(first cut done: `reposhield serve` – FastAPI, SQLite queue, webhook, status+comment reporting, dashboard)**
Remaining in Phase 2:
- GitHub **App** + Check Runs with line annotations (installation tokens instead of a PAT)
- Postgres + Redis/Arq in place of SQLite + in-process threads; rate limiting; per-user auth/SSO
- run the docker backend on a dedicated runner host, not the API host

Original plan (keep the same `engine.verify()` core, do not fork it)
1. FastAPI service: `POST /webhook` (validate GitHub signature, enqueue), `GET /runs`, `GET /runs/{id}`; Postgres for runs/findings; Redis/RQ or Arq queue; idempotency key = `result["fingerprint"]["idempotency_key"]`.
2. GitHub **App** + Check Runs with line annotations (the Action already gives you the gating story without it).
3. Minimal React dashboard reading the existing `result.json` / `events.jsonl` schema (HTML report is the design reference).
4. Reporter isolation: write test results through a channel the test process cannot forge.

Phase 3 – depth
1. Symbol-level graph (function/class), `TESTS` edges from coverage per test function, pytest-node-level selection.
2. Optional LLM *explainer* only: summarise findings for humans. It never sees secrets, never changes verdicts, and its output is stored separately from evidence.
3. TypeScript adapter behind the same `LanguageAnalyzer` shape (`analyzer.py` is already the single seam).
4. gVisor/Firecracker runner; controlled egress proxy; per-repo resource quotas.
