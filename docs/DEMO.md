# Presenting RepoShield (≈7 minutes)

## Pre-flight (do this 10 minutes before, not live)
```
pip install -e ".[dev]"          # installs pytest + coverage into the SAME Python that runs reposhield
reposhield doctor                # every line should be [ ok ] or an understood [warn]
reposhield demo ./demo
cd demo
reposhield showcase              # dry run: all 10 rows should match their "expected" column
```
* Windows: the dev sandbox has timeouts and a scrubbed environment but **no memory/CPU limits and no network isolation**.
  Say so if asked; it is shown in every report under "sandbox".
* If Docker Desktop is running, RepoShield still uses the dev sandbox unless you built the runner image
  (`docker build -t reposhield-runner:py312 -f runner/Dockerfile .`) — so the demo behaves the same either way.
* Keep two terminals: one for commands, one with `demo/.git/reposhield/runs/<id>/report.html` open in a browser.

## Story (problem → proof → control → honesty)

**1. The problem (30 s).** "AI agents now open pull requests. Reviewers can't tell what a 400-line agent diff actually
affects, and CI only runs whatever tests someone remembered to wire up. RepoShield independently checks the *change itself*."

**2. A safe change is fast (60 s).** `reposhield verify --base main --head pr/safe-refactor`
→ PASS, 2 of 9 test files run (78% fewer), graph updated by re-reading 1 file. Point at *why* each test was chosen:
`reposhield test-plan --base main --head pr/safe-refactor`.

**3. It catches what review misses (2 min).**
* `pr/transitive-leak` → BLOCK. "The agent never touched `payments/`. It changed a shared helper that payments depends on,
  which now imports analytics. Here is the dependency path." (Show the `via` chain.)
* `pr/weakened-tests` → REVIEW_REQUIRED. "Every test passed — because the agent skipped the one that would have failed.
  CI is green; RepoShield is not." ← the strongest slide for an AI-agent audience.
* `pr/policy-tamper` → BLOCK. "The agent deleted the rule that forbids its change. Rules are read from the base branch."
* `pr/real-bug` → BLOCK. Tests run in a sandbox and the required auth tests fail.

**4. Evidence, not opinions (60 s).** Open the HTML report: findings, selected tests with reasons, impact paths, audit chain.
`reposhield audit verify <run_id>` → intact. Edit one line of `events.jsonl` → run again → TAMPERED.

**5. Controlling the agent, not just the PR (60 s).**
```
reposhield action authorize --cmd "pytest tests/auth"      # prints a signed, expiring, single-use token
reposhield action exec --cmd "pytest tests/auth" --token <T>   # runs
reposhield action exec --cmd "pytest tests/auth" --token <T>   # DENIED: replay
reposhield action authorize --cmd "rm -rf /"               # DENIED: default-deny
```

**5b. It is a service, not just a CLI (60 s).** `reposhield serve --allow-local <folder containing the demo>` → open
`http://127.0.0.1:8080`, paste the demo repo path, base `main`, head `pr/transitive-leak`, Verify. The run appears, flips from
*queued* to *BLOCK*, and its page shows the report plus a live "audit chain: intact" check. Mention: the same engine handles
GitHub PR webhooks and posts a commit status + comment; submitted code never runs without the docker sandbox.

**6. Honest status + ask (60 s).** Show the numbers and limits slide (below), then the ask.

## Numbers you can quote (and their limits)
| Claim | Evidence | Say this caveat |
|---|---|---|
| Incremental graph 12× faster than rebuild (2,000 files) | `python benchmark/bench.py` | synthetic repo; result checked identical to full rebuild |
| Selective tests: 12/12 seeded bugs caught with 68% fewer tests | same script | 9-test demo app — a sanity check, not a result at scale |
| Filename heuristic misses 2/12 | same script | shows *why* a dependency graph is needed |
| 10/10 demo scenarios give the expected verdict | `reposhield showcase`, e2e tests | scenarios are ours, not a third-party benchmark |

## Questions you will probably get
* **"Why not just CI?"** CI runs what you configured; it can't tell that a test was skipped to get green, that a transitive
  dependency crossed a boundary, or that the rules were edited by the PR itself.
* **"Does it use AI?"** The core deliberately does not — verdicts must be reproducible and auditable. An LLM explainer is
  planned for summaries only and can never change a verdict.
* **"Is it secure?"** Say: "The control logic is. Isolation of untrusted code is the open item": dev sandbox today,
  hardened Docker backend written and unit-tested but not yet run end-to-end, microVM later. See `docs/SECURITY.md`.
* **"Other languages / scale?"** Python-only, file-level today (one adapter seam: `analyzer.py`). Scale is unproven beyond the benchmark.
* **"Existing tools?"** Adjacent: policy-as-code and CI gates exist; the gap targeted here is *agent-specific* checks (test
  weakening, self-edited policy, transitive boundaries, signed action gateway). Don't claim novelty beyond that without checking.

## The ask
"Approve ~2 weeks: (1) run the Docker backend end-to-end and add symbol-level impact — *hardening*; (2) a FastAPI service,
GitHub App check runs and a small dashboard — *Phase 2*. Success = a pilot on one real repo with measured false-block rate."
