# RepoShield five-week implementation tasks

Authoritative backlog for the solo-builder deadline. Supersedes `IMPLEMENTATION_BACKLOG.md`. Read `REPOSHIELD_MASTER_PLAN.md` and `COST_ESTIMATE.md`. Estimates are rough focused-work ranges, not guarantees. Total of the estimates below is 95–129 hours, including final hardening; allow roughly 110–145 hours with contingency. Keep optional work outside that budget.

## RS2 01 Baseline and scope contract

Estimate 4–6 hours. Preserve current code and user changes. Confirm source-control location; the earlier inventory had no top-level `.git`. Establish a clean test environment and record exact dependencies, interpreter and baseline. Preserve the ten demo scenarios. Create `docs/IMPLEMENTATION_STATUS.md` and a threat model identifying trusted coordinator, broker, agent, sandbox and protected resources.

Acceptance: baseline failures are explained honestly; supported modes and exclusions are recorded; no Go rewrite, LLM service or cloud purchase begins. Document the previous 111-pass/one-skip result as historical until reproduced.

## RS2 02 Verification integrity fixes

Estimate 6–8 hours. Depends on 01. Add explicit required-test semantics for skips/xfails/empty collection. Version result and action schemas. Add all trust-relevant inputs to fingerprints and use distinct attempt directories. Disable unsafe cached gate reuse until signed persistence is ready. Preserve pure algorithm interfaces.

Acceptance: stricter verification cannot reuse weaker local evidence; all-skipped required tests never satisfy a passing requirement; concurrent equivalent requests do not overwrite active output; normal demo scenarios retain intended results.

## RS2 03 Durable database and worker foundation

Estimate 8–10 hours. Depends on 01–02. Add PostgreSQL migrations for repository, run, attempt, task, session, decision, execution, events and outbox. Implement a separate worker process with transactional job claim, lease, heartbeat, bounded retries and fixed stage dependencies. No Redis needed now.

Acceptance: two workers cannot both finalize the same lease; a restart recovers abandoned verification work; duplicate logical requests have one identity but explicit reruns create distinct attempts. Role/session checks guard access, initially with distinct locally configured development identities; GitHub sign-in replaces their UI transport in task 10. Never expose anonymous action/approval endpoints. No untrusted code executes on the API host.

## RS2 04 Typed action policy and approval

Estimate 7–9 hours. Depends on 02–03. Define READ_FILE, APPLY_PATCH and RUN_TESTS; production DB and unrestricted network requests are denied. Resolve resource identities from trusted configuration. Effective permissions intersect administrator constraints, repository rules and session scope. Implement review-required state for one narrowly defined reviewable operation.

Acceptance: valid read/patch/test requests can proceed; unsupported actions return a clear denial; a repository cannot grant itself production permissions; agent identity cannot approve its own action; hard denial cannot be bypassed by an approval button.

## RS2 05 Signed decision and atomic claim

Estimate 7–9 hours. Depends on 04. Use maintained Ed25519 primitives and versioned canonical serialization. Keep signing private key outside repository and executor. Bind identity, exact parameters, snapshot, resource/profile, image, limits, policy epoch and expiry. Add executor audience and key ID. Atomically claim a decision/nonce and create execution state.

Acceptance: changed field, expired token, wrong resource/session, changed policy, revoked session and stale snapshot deny. A concurrent replay test has exactly one successful claim. Crash after claim yields unknown outcome, not automatic execution replay. Document that atomic claim does not prove exactly-once external effects.

## RS2 06 Real restricted execution

Estimate 10–14 hours. Depends on 03–05. Run broker on dedicated Linux execution environment. Build/pin image; enforce non-root, no platform secrets, no Docker socket inside sandbox, no host integration, network denial, CPU/RAM/PID/disk/runtime/output caps. Use immutable source snapshots and isolated temporary test copies; patches create new snapshots. Dependencies are prepared under the same untrusted-code model, with controlled setup access and no privileged credentials.

Acceptance: real Linux tests establish the configured isolation properties; denied/invalid authorization cannot start a job; test code cannot mutate the authoritative workspace; timeout and error remove processes/containers. Missing image/dependencies/isolation stays non-successful. Test output and coverage files are bounded and treated as hostile.

## RS2 07 Protected database and bypass demonstration

Estimate 5–7 hours. Depends on 06. Create synthetic e-commerce fixtures and a protected database with independently owned credentials. Run allowed edit/tests, explicit denied database action, and bounded direct-access/network fixtures. Record table existence, row counts and content digest using a trusted verifier outside the sandbox.

Acceptance: allowed workflow completes; explicit request denies; direct access also fails; database state is unchanged. Tests distinguish policy denial from network/credential enforcement. The demo never uses real customer data. A fixed staging read operation is optional, not a prerequisite.

## RS2 08 Authenticated evidence and history

Estimate 6–8 hours. Depends on 03, 05–07. Sign canonical manifest with result/artifact hashes, exact context, event count and final head. Checkpoint in trusted PostgreSQL. Verify cache eligibility against signature and checkpoint. Add session/decision/execution events and redaction; limit retained logs.

Acceptance: result replacement, audit truncation, event reorder and wrong-run/tenant copying fail. Replay view reconstructs evidence without executing. Documents distinguish evidence authenticity from semantic truth of malicious test results.

## RS2 09 Real GitHub App and merge gate

Estimate 10–14 hours. Depends on 02–03, 06, 08. Implement one installation and repository onboarding, installation token flow, webhook HMAC validation, atomic delivery/run intake, Checks API publication and retry outbox. Bind to current head and trusted policy; stale result cannot update another commit. Provide public-demo branch-protection setup.

Acceptance: real PRs show pass, block, review-required and infrastructure failure correctly. Required gate permits only eligible success. Duplicate webhook and reordered A/B commits behave correctly. Revoke installation access and prove scheduling stops. Do not claim merge-queue support without its separate event validation.

## RS2 10 Minimal authenticated product UI

Estimate 8–12 hours. Depends on 03–09. Add GitHub sign-in and one-organization administrator/reviewer/viewer roles. Build repository list, run detail, controlled session/actions, policy/settings views. Use actual stored data. Default to existing HTML if React setup threatens the deadline.

Acceptance: reviewer sees why an action or change was denied, can approve only a permitted exact request, sees execution state and audit. Backend authorization blocks changing object IDs to another repository. No credentials in browser storage or rendered logs. Include empty/loading/error states.

## RS2 11 Evaluation and submission material

Estimate 12–16 hours. Depends on 02 and 06–10. Extend to at least 20 change scenarios and 15 control scenarios. Measure full/selected tests, detection, graph equivalence/performance, scheduler overhead and authorization overhead. Save raw inputs/results with environment versions. Write the report, architecture, threat model, algorithm description, deployment guide and limitations.

Acceptance: reported numbers come from reproducible runs, not original research examples. Positive actions and safe changes pass, risky/unknown cases receive intended outcomes, misses/flakes are disclosed. Another person can operate the demo using the guide.

## RS2 12 Freeze and release

Estimate 12–16 hours. Depends on 01–11. Fix defects only; package pinned installs/images, run fresh-machine rehearsal, test cleanup/restart/backup restore, finalize the eight-minute demo and record a fallback video. Optional cloud deployment uses an explicitly selected budget profile.

Acceptance: full demo works twice from clean state; no secrets in artifacts; no mocked production results; costs/retention/teardown documented; known limitations explicit. No paid resource is provisioned without user authorization for its concrete cost and scope.

## Daily working protocol

Codex should read status, select the next dependency-ready task, implement a bounded change, run meaningful tests and update evidence. The human builder should review the behavior and understand the design, especially authorization, paths, nonce transactions and isolation. Keep the release runnable after each task.

Week one targets 01–03; week two targets 04–07; week three targets 08–09 and starts 10; week four completes 10–11 and starts 12; week five is remaining 12 and contingency. Estimates are a planning constraint: if work exceeds budget, cut optional UI/adapter work promptly.

## Stop conditions and permitted cuts

Do not ship a controlled-mode claim if the agent retains independent privileged access, private signing keys appear in execution, token replay succeeds, or direct protected-resource access bypasses the gateway. Do not ship merge enforcement without actual GitHub validation. If blocked on paid hosting, continue local work and list the exact external setup required.

Permitted cuts: React migration (retain existing HTML views), interactive graph, staging-data read, live LLM adapter, external repository benchmark expansion, convenience filters, visual policy editor. Mandatory positive/negative controls, evidence integrity and accurate limitations are not permitted cuts.
