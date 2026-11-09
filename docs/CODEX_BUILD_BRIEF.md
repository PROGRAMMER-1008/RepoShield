# RepoShield implementation handoff

Version 2, 10 October 2026. Copy the request below into Codex in this project. It supersedes the earlier PR-only emphasis. This is a handoff document, not an automatically active AGENTS.md file.

---

Build RepoShield as a deterministic verification and controlled-execution platform for AI coding agents. The product has two equally necessary modes: independently verify proposed code changes, and authorize/restrict connected agent actions before execution. Do not postpone the action gateway to a future release.

Read these files in order:

1. `docs/REPOSHIELD_MASTER_PLAN.md`
2. `docs/BUILD_TASKS_V2.md`
3. `docs/COST_ESTIMATE.md`
4. Existing prototype code, tests and applicable repository instructions.

The original research is preserved in `docs/ACV_ORIGINAL_RESEARCH.md`. Use it for intent and traceability. The version 2 plan resolves its scope and technology choices for this deadline. `PRODUCT_BUILD_PLAN.md`, `IMPLEMENTATION_BACKLOG.md` and `CODEX_BUILD_BRIEF_V1_ARCHIVED.md` are superseded; do not follow their longer schedule or defer action control.

Constraints: I am the only active builder, have a 16 GB laptop and must submit in 4–5 weeks. Four people share costs, but they are not four developers. Preserve the existing Python prototype. Keep the `reposhield` CLI and `.reposhield.yml`. Do not rewrite the backend in Go. Use PostgreSQL for durable jobs and atomic action claims; Redis/Celery, a large React dashboard and LLM features are not prerequisites for the submission.

Start with RS2 01 and RS2 02. Inspect source-control state and preserve user changes. Reproduce the baseline in a clean environment, establish typed verification/action contracts and trust boundaries, then fix required-test and cache-integrity weaknesses with regression tests. The previous 111 passed/one skipped result is historical; rerun rather than claiming it as current. Create `docs/IMPLEMENTATION_STATUS.md` with commands, results, limitations and the next task. Complete these first two tasks before expanding scope.

Mandatory product behavior:

- Change verification produces PASS, BLOCK or REVIEW_REQUIRED with exact input fingerprints. Unknown/missing mandatory evidence cannot become PASS. Infrastructure status remains separate.
- Controlled mode supports typed reads, patches and approved test tasks. Unsupported network and production database operations deny. Do not implement arbitrary shell-string safety through keyword matching.
- Agent policy cannot enlarge administrator permissions. Private signing keys, production credentials and platform secrets never enter the workspace or sandbox.
- Use signed, expiring decisions bound to identity, action parameters, workspace revision, runner profile, policy and limits. Atomically consume the authorization once. Changed inputs, replay, revocation and stale policy deny.
- Prevent bypass using the actual execution environment: no independent privileged tool route, no production credentials, no host/Docker socket access and no unrestricted egress. A gateway an unrestricted agent can ignore is not controlled execution.
- Treat dependency installation and pytest as arbitrary code execution. Use real Linux isolation, bounded resources and isolated copies of immutable snapshots. Test fixtures cannot write authoritative evidence directly.
- Demonstrate a synthetic protected database remaining unchanged after both a denied action request and a direct-access attempt. Verify database state independently. Never use real production data.
- A raw result remains immutable; human approval is separate, narrowly scoped and invalidated by input/policy changes. The agent cannot approve itself and hard denials cannot be overridden.
- GitHub enforcement must be tested on a real synthetic repository. A stale run cannot satisfy a current check, and unresolved review must not map to neutral/skipped success.
- The deterministic core and both modes must work without an LLM. Scripted agent clients are labeled honestly; policy decisions, executions, graphs and metrics must be real.

Keep algorithms separate from storage/HTTP/execution adapters. Use small reviewable changes with meaningful positive and negative tests. Run real isolation and GitHub checks at their milestones; mocks alone do not satisfy those acceptance criteria. Do not claim a passed test suite proves security against every malicious program.

Plan for a complete local demonstration by week three, submission readiness by week four and hardening in week five. If time slips, retain existing HTML views instead of building React, and cut interactive graph/live-model polish before cutting enforcement or evidence integrity.

Spend no money and provision no paid service merely because it appears in the cost estimate. Work locally first. When external setup is necessary, finish local preparation and identify the concrete provider/resource, duration, expected total and teardown plan before requesting purchase approval. Missing accounts or credentials must be reported, never fabricated.

Proceed with RS2 01–02 now. At completion, report changed behavior, actual tests, unresolved limits and readiness for RS2 03.

---

## Next milestone prompt

Read the version 2 plan, backlog and implementation status. Complete the next dependency-ready task in `BUILD_TASKS_V2.md`. Preserve both verification and controlled execution, run its acceptance checks, and update status with evidence. Do not add paid infrastructure or optional features without an explicit need and authorization.
