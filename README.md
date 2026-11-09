# RepoShield

Implementation status: [RS2 01–10 locally, with VM and live GitHub acceptance pending](docs/IMPLEMENTATION_STATUS.md). Both deterministic
verification and controlled agent execution are release requirements. The current
command gateway is a development prototype; controlled-session enforcement is not
yet complete. See the [trust boundaries](docs/THREAT_MODEL.md) before executing code.
Unsigned gate-cache reuse is disabled; every verification creates a fresh attempt.
The PostgreSQL coordinator and separate static worker have a
[local setup guide](docs/LOCAL_COORDINATOR.md). `serve` uses that configuration by
default; the prior SQLite/HTML service requires `--legacy-dev-server` explicitly.
The [typed action policy and review API](docs/ACTION_POLICY.md) uses external trusted
configuration. [Signed authorization and atomic claims](docs/SIGNED_AUTHORIZATION.md)
are implemented; actual isolated execution remains RS2 06.

RS2 06 now has a [real Docker Desktop development broker](docs/RESTRICTED_EXECUTION.md)
with signed claims, immutable snapshots and restricted test containers. Dedicated
Linux VM acceptance remains pending; this is not a completed controlled deployment.
RS2 07 adds a [real protected synthetic database demonstration](docs/PROTECTED_DATABASE_DEMO.md)
with policy denial, direct-access checks and independent before/after data hashes.
Dedicated-host acceptance remains pending for both phases.
RS2 08 adds [signed evidence and authenticated replay](docs/AUTHENTICATED_EVIDENCE.md)
with trusted PostgreSQL checkpoints and scoped history. Automatic cache reuse remains disabled.
RS2 09 adds the [GitHub App and Checks publication path](docs/GITHUB_APP.md), including
durable signed-webhook intake, scoped installation tokens, live synthetic-repository
PASS/BLOCK/REVIEW_REQUIRED checks, installation suspension denial/recovery, and a
real stale-publication race check. Dedicated-host and independent bypass inspection
remain pending.
RS2 10 adds the [authenticated product UI](docs/AUTHENTICATED_UI.md) at `/ui`, with
GitHub organization sign-in, scoped human roles, real run/session history and
exact-request approval. OAuth sign-in was validated with the synthetic demo org.

**Let AI coding agents move fast without giving them unrestricted authority over your repository.**

RepoShield sits between an AI-generated change and your protected branch. It does *not* ask an LLM whether the code looks good.
It independently, deterministically works out **what the change touches, which rules it violates, which tests actually matter,
and whether those tests pass in a sandbox** — then returns `PASS`, `BLOCK` or `REVIEW_REQUIRED` with evidence.

```
git diff ─► incremental dependency graph ─► impact ─► policy + built-in checks ─► test selection
        ─► sandboxed run ─► deterministic verdict ─► report + hash-chained audit log
```

* An unknown is never a pass: no evidence ⇒ `REVIEW_REQUIRED`.
* Rules are loaded from the **base branch**, so an agent cannot edit its own judge.
* No LLM in the core. (An optional explainer is a roadmap item and can never change a verdict.)

## Quick start (2 minutes)

```bash
pip install -e ".[dev]"            # needs Python 3.10+, git
reposhield demo ./demo             # builds a repo with a healthy main + 10 "AI agent PR" branches
cd demo
reposhield showcase --open         # verifies all 10 branches, prints one table, opens an HTML index
reposhield verify --base main --head pr/safe-refactor      # PASS  – 2 of 9 test files run
reposhield verify --base main --head pr/transitive-leak    # BLOCK – payments → common.money → analytics
reposhield verify --base main --head pr/weakened-tests     # REVIEW_REQUIRED – tests pass, but a test was skipped
open .git/reposhield/runs/*/report.html                    # evidence, impact, audit timeline
```

| Demo branch | What the "agent" did | Verdict |
|---|---|---|
| `pr/safe-refactor` | small guard in `payments/refund.py` | PASS (selective tests) |
| `pr/analytics-leak` | `payments` imports `analytics` | BLOCK |
| `pr/transitive-leak` | indirect dependency via `common/money.py` | BLOCK (shows the path) |
| `pr/secret-and-workflow` | hard-coded AWS key + new CI workflow | BLOCK |
| `pr/real-bug` | removed token-expiry check | BLOCK (required auth tests fail) |
| `pr/policy-tamper` | deleted the isolation policy, then violated it | BLOCK (policy comes from base) |
| `pr/weakened-tests` | removed a guard **and** skipped the test that catches it | REVIEW_REQUIRED |
| `pr/new-dependency` | added a package | REVIEW_REQUIRED (+ full suite) |
| `pr/prod-config` | touched production config | REVIEW_REQUIRED |
| `pr/docs-only` | README | PASS, no tests needed |

Exit codes: `0` PASS · `1` BLOCK · `2` REVIEW_REQUIRED · `3` tool error.

## What a reviewer sees
Every run writes an evidence report with a plain-English verdict, summary tiles, a **visual impact map** (who depends on whom, the rule-breaking path in red, the changed file tagged, tests that cover each file as badges) and the audit chain.
`reposhield showcase --open` builds a demo gallery page that runs all ten scenarios and links each report. Architecture and pipeline diagrams are in `docs/figures/`.

## Commands

| Command | Purpose |
|---|---|
| `reposhield init` | write a starter `.reposhield.yml` |
| `reposhield policy validate` | validate the policy file |
| `reposhield analyze` | files / tests / functions / edges |
| `reposhield graph [--impact FILE…] [--format dot]` | dependency graph, reverse impact with paths |
| `reposhield test-plan --base B --head H` | which tests would run and **why** |
| `reposhield verify --base B --head H` | full pipeline (`--format json\|markdown`, `--strategy safe\|balanced`, `--no-tests`, `--sandbox docker`) |
| `reposhield doctor [--sandbox docker]` | check the environment and *prove* what the sandbox enforces (secrets hidden, timeout, output cap, network, read-only fs) |
| `reposhield showcase [--open]` | verify every `pr/*` branch of the demo repo, summary table + HTML index |
| `reposhield baseline` | build coverage-based test→code map (for `--strategy balanced`) |
| `reposhield audit verify RUN` / `audit show RUN` | prove / inspect the audit chain |
| `reposhield action authorize\|exec --cmd "…"` | agent action gateway (signed, single-use, default-deny) |

## Policies (`.reposhield.yml`)

```yaml
policies:
  - id: payment-isolation
    severity: critical            # critical/high ⇒ BLOCK · medium ⇒ REVIEW · low ⇒ info  (override with on_fail)
    when: {changed: ["payments/**"]}
    rules:
      - {type: forbidden_import, from: "payments/**", to: "analytics/**", transitive: true}
  - id: auth-tests
    severity: high
    when: {changed: ["auth/**"]}
    rules: [{type: required_test, paths: ["tests/auth/**"]}]   # must be selected, run AND pass
```
Rule types: `forbidden_path`, `forbidden_import` (repo paths via `to:` — direct or transitive — and/or package names via `modules: [requests, "boto3.*"]`; only *newly introduced* violations are blamed),
`required_test`, `require_review`, `max_changed_lines`, `test_mode`, `forbidden_command`.

Built-in checks (no config needed): secret scan of added lines (redacted output), dependency-manifest changes, Python syntax,
**test integrity** (deleted / removed / assertion-reduced / newly-skipped tests — a classic agent shortcut), policy-file tampering.

## What was measured (`python benchmark/bench.py`)

* **Incremental graph vs full rebuild**, 2,000 files / ~10k edges, 5 files changed: **0.064 s vs 0.767 s (12×)**, and the
  incremental graph is asserted identical to a full rebuild (also property-tested over random edits).
* **Test selection vs 12 seeded bugs** in the demo app (9 test files): full suite 12/12 caught; **`safe` 12/12 caught using
  on average 2.8 files (68% fewer)**; filename heuristic ("test_<module>.py") used 0.9 files but **missed 2 of 12** bugs.
  `balanced` equalled `safe` here — the demo is too small to show a difference. Treat these as a sanity check, not a result at scale.

## Service mode (Phase 2): API + GitHub webhook + dashboard

```bash
pip install -e ".[server]"
reposhield serve --allow-local ~/projects          # Windows: --allow-local C:\Users\you\Desktop
# open http://127.0.0.1:8080  -> live dashboard, "Verify a local repository" form, per-run report + audit-chain check
```
| Endpoint | Purpose |
|---|---|
| `GET /` · `GET /runs/{id}` | dashboard (verdict counts, run list, embedded sandboxed report, live audit-chain check) |
| `POST /api/v1/verify` `{repo_path, base, head}` | queue a local verification (only under `--allow-local` roots) |
| `GET /api/v1/runs` · `/runs/{id}` · `/runs/{id}/report` · `/runs/{id}/audit` | results, HTML report, hash-chain verification |
| `POST /webhooks/github` | signed GitHub `pull_request` events → queue → verify → commit status + PR comment |
| `GET /api/v1/health` | liveness + queue stats |

GitHub setup: webhook (content type JSON, event *Pull requests*) → `https://<host>/webhooks/github`; export
`GITHUB_WEBHOOK_SECRET` (same secret) and `GITHUB_TOKEN` (fine-grained: *Commit statuses* + *Pull requests* write, *Contents* read);
start with `--allow-repo owner/name --public-url https://<host>`. Make the **reposhield** status a required check.
**Fail-closed defaults:** webhooks are off without a secret; repos must be allow-listed; code submitted via webhook is only executed
behind the docker sandbox (otherwise the PR is `REVIEW_REQUIRED` with static findings); non-loopback binds require `REPOSHIELD_API_TOKEN`.

## Status & honest limits
Works on Linux/macOS/Windows (Windows: dev sandbox has timeouts + scrubbed env only — no memory/CPU limits, no network isolation). See [docs/DEMO.md](docs/DEMO.md) for a presentation script.
Python-only, file-level graph, test-file-level selection. The subprocess sandbox is a **dev backend**; the docker backend is
implemented (hardened flags, unit-tested command line) but **not yet run end-to-end**, and the GitHub Action is **not yet run on
a live PR**. Full list in [docs/SECURITY.md](docs/SECURITY.md). Next steps in [docs/ROADMAP.md](docs/ROADMAP.md).

## Layout
`reposhield/server/` — `app` (FastAPI) · `worker` · `db` (SQLite) · `github` · `dashboard`  
`reposhield/` — `analyzer` (AST) · `graph` (incremental, impact) · `policy` · `checks` · `selector` · `sandbox` · `engine` (pipeline) ·
`verdict` · `audit` · `actions` (gateway) · `coverage_map` · `report` · `cli` · `demo`  
`tests/` (112 tests incl. e2e over all demo scenarios) · `benchmark/` · `integrations/github-action.yml` · `runner/Dockerfile`

The submission candidate passed the full local suite on 1 November (406 passed,
1 Windows symlink case skipped, 0 failed), plus real Docker Desktop controlled
execution checks. See [submission guide](docs/SUBMISSION_START_HERE.md) for exact
scope, reproducible evidence, archive identity and remaining gates. The current
offline archive is a submission candidate, not dedicated-Linux or production
security certification.
