# RepoShield implementation backlog

> SUPERSEDED: Do not execute this backlog as the current plan. Use `BUILD_TASKS_V2.md` with `REPOSHIELD_MASTER_PLAN.md`. Controlled execution is now mandatory in the submission release, and the timeline is 4–5 weeks for one developer.

Read `PRODUCT_BUILD_PLAN.md` first. Each ticket is one bounded implementation task or a small series of pull requests. Dependencies are mandatory; do not build the dashboard before proving the gate. Estimates in the main plan apply to milestones, not individual tickets.

## Milestone 0 Reproducible foundation

### RS 001 Establish the baseline

Inspect existing instructions, repository status and toolchain. Preserve the prototype. Confirm the intended Git repository and create version control if needed. Lock Python dependencies in a clean environment. Run current tests, record runtime, platform and failures, and classify environment failures separately. Add a reproducible Linux CI baseline and a Windows compatibility job. Reconcile README/synopsis claims against actual evidence. Deliver `docs/BASELINE.md` with commands and results.

Acceptance: a fresh documented checkout runs the same baseline; no claim that all tests pass unless the actual invocation passes. Do not remove failing assertions to make the baseline green.

### RS 002 Define verification contracts

Add versioned typed models for inputs, findings, test plans, execution observations, results and manifests; preserve CLI compatibility or provide an explicit schema migration. Separate run status from verdict. Define PASS, unknown and required-test outcome semantics. Document policy provenance, merge-base/head/base-tip/execution-tree roles.

Acceptance: contract fixtures round-trip; invalid/missing evidence cannot aggregate to success; local development and enforced modes have explicit assurance labels.

### RS 003 Close decision and cache defects

Add reproductions for all-skipped required tests, xfails, missing reports, empty collection, and trust-sensitive cache reuse. Bind every decision-affecting input to the fingerprint. Separate run identity from attempt paths; stop overwriting active run directories. Cache reuse must validate result artifact integrity as well as events. Until authenticated persistence exists, avoid treating mutable local cached results as trusted gate evidence.

Acceptance: a prior low-assurance/local run cannot satisfy stricter enforcement; different runner digests and requirements invalidate eligibility; concurrent equivalent requests do not corrupt artifacts.

## Milestone 1 Real execution

### RS 004 Specify and validate runner isolation

Write threat model and execution protocol. Separate trusted coordination from submitted code. Build a pinned Linux runner image. Test non-root execution, no platform secrets, no Docker socket, network denial, filesystem restrictions, CPU/memory/PID/disk limits, timeout cleanup and output caps using bounded fixtures.

Acceptance: complete demo verification runs inside the actual intended Linux backend; unavailable isolation yields non-success. Record kernel/image/runtime configuration. Do not equate unit tests of command arguments with real isolation tests.

### RS 005 Prepare dependencies safely

Define supported lockfile/dependency flows and an isolated preparation job with restricted package access. Fingerprint prepared environments. Never execute setup hooks on the API host. Scope writable caches to a tenant/environment; test cleanup and size bounds.

Acceptance: a pinned pytest project runs with test-stage network disabled; altered lockfiles build distinct environments; failed dependency installation cannot yield PASS. Unsupported network-dependent tests are explained.

### RS 006 Strengthen test evidence

Implement bounded parsing of result/coverage artifacts, expected collection comparison where supported, immutable trusted harness material and externally collected process observations. Redact output before persistence. Model missing/forged/unparseable output as incomplete or invalid. Document remaining malicious-test limitations.

Acceptance: symlink/oversized/malformed report fixtures and premature process exit do not produce a trusted pass; secrets in ordinary failure output are not exposed by reports. Never claim complete secret detection.

## Milestone 2 GitHub vertical slice

### RS 007 Add GitHub App lifecycle

Replace production PAT flow with installation authentication; keep private keys out of execution. Handle install/uninstall, repository access changes, token expiration and revocation. Use bounded signature-verified webhook intake. Fetch only validated GitHub repository identities and exact revisions with credentials not exposed on process command lines.

Acceptance: two installations are isolated; a revoked installation stops scheduling; fork PR access failures are visible and non-successful; no sensitive token appears in logs.

### RS 008 Publish and enforce Checks

Add separate observe and gate checks; line annotations and links. Persist publication retries. Map incomplete review to non-success. Add explicit revision supersession and target-branch invalidation. Document required-check/App setup. Either support merge groups or state they are unsupported.

Acceptance: real GitHub test PRs prove PASS permits the configured gate and BLOCK, REVIEW_REQUIRED, infrastructure error and stale revisions do not. Record URLs/screenshots as private validation evidence, with secrets removed. A simulated API test is not the real gate validation.

### RS 009 Replace prototype Action template

Provide a working pinned release installation, reviewed action SHAs, immutable revision inputs and explicit dependency-error handling. Separate credentials from untrusted execution. Explain trust limits if operating without the hosted coordinator.

Acceptance: copy the template into a clean sample repo and run it successfully and unsuccessfully; no placeholders in the release template and no ignored setup errors.

## Milestone 3 Durable coordination

### RS 010 Migrate to PostgreSQL

Implement Alembic migrations and typed repository access for workspace, installation, repo, delivery, run, attempt, finding, artifact and outbox records. Preserve SQLite only as a local legacy mode if useful; production has one authoritative state store.

Acceptance: empty database migration, backup/restore and a version-upgrade migration work; delivery IDs and tenant-owned foreign keys have enforced constraints.

### RS 011 Deliver jobs reliably

Persist delivery/run/outbox atomically. Add Celery/Redis dispatch with database leases, heartbeat, bounded retry and fencing tokens. Finalization requires the current lease; abandoned workers cannot overwrite a newer result. Make task and GitHub publication independently retryable. Add a sweeper for stalled leases and inspectable permanent failures.

Acceptance: simulated crashes before/after enqueue, duplicate delivery, Redis restart, worker restart and failure after evidence upload all converge to a valid terminal state without false green or duplicate side effects.

### RS 012 Authenticate evidence

Store artifacts in object storage; create canonical signed manifests and trusted event checkpoints. Verify hashes, sizes, count, tenant ownership, run identity and signature before reuse. Add key IDs and rotation support. Use unique attempt prefixes and retention metadata.

Acceptance: replacing result bytes, truncating/reordering events, copying a valid manifest to another run/tenant and using an unknown key fail verification. A valid completed artifact remains verifiable after signing-key rotation according to the documented retention policy.

## Milestone 4 Usable team product

### RS 013 Add identity and authorization

Implement GitHub login, secure server sessions, CSRF protection and owner/maintainer/viewer membership. Resolve installation ownership explicitly. Protect every run, repo, artifact, runner and admin route. Add rate and request-size limits; disable local-path APIs in cloud mode.

Acceptance: an explicit role matrix passes; changing IDs never grants another workspace's data or operations; removed members lose access; runner credentials can be revoked.

### RS 014 Build dashboard

Implement setup, repository overview, run detail, policy view and team/runner settings in React/TypeScript. Use real API responses. Render graph paths from structured evidence; retain downloadable HTML/JSON. Include keyboard navigation and loading/error/empty/stale states.

Acceptance: browser test installs/configures a test workspace, views a run and follows an actionable finding; private artifacts cannot be accessed after logout; no mock metrics presented as real usage.

### RS 015 Add policy onboarding and modes

Add versioned starter templates, validation, trusted enrollment and observation-to-enforcement transition. Policy changes require normal trusted approval. Display suppressed findings and expiration; defer approval override API unless revision-bound semantics are implemented completely.

Acceptance: policy editing in a PR cannot change that PR's judge; fresh repositories cannot self-enroll from untrusted code; observation checks are distinct from merge gates.

## Milestone 5 Measured release

### RS 016 Build evaluation corpus

Pin real repositories and historical/seeded changes. Compare full, filename, static and experimental coverage selection under identical environments. Export raw timings and outcomes, mark flakes and exclusions, and run incremental/full graph equivalence properties.

Acceptance: another person reproduces documented results; report selection misses and unsupported cases, not only successes; do not repeat prototype reduction percentages as new measurements.

### RS 017 Add operations and release packaging

Add quotas, metrics, alerts, retention/deletion, backups, restore procedure, installation guide, incident runbook and a versioned packaged CLI. Decide license and audit dependency licenses before public distribution. Verify install from a built artifact, not only editable source.

Acceptance: fresh installation, worker failure recovery, installation removal, data deletion and restore drill succeed; deployment can roll back without corrupting schema or evidence.

### RS 018 Run design partner pilots

Recruit and onboard 3–5 teams, establish consent and data handling, start in observation mode and review findings weekly. Measure activation, weekly retention, noise, useful findings, run cost and willingness to pay.

Acceptance: pilot report contains observed usage and feedback; feature priority changes reflect evidence. No production-readiness claim based solely on a student demo.

### RS 019 Add paid-beta controls

Only after retained pilot usage: implement plan entitlements, metered usage, quota enforcement, invoicing/payment integration, cancellation and support workflow. Payment processing remains with a provider; never store card data.

Acceptance: signed duplicate billing events are idempotent, plan changes and quota exhaustion behave predictably, and measured gross margin supports the offered usage. Obtain provider/account details when needed; no fabricated credentials or live billing tests.

## Release stopping rules

Do not launch an enforced gate with unknown-outcome success, mutable trusted inputs, cross-tenant access, execution on the API host, or absent real GitHub gate validation. Do not launch public hosted code execution merely because a Docker command has restrictive flags. When a gate fails, fix it or explicitly reduce the advertised deployment/support scope.
