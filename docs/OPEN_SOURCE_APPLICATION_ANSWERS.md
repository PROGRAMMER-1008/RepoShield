# Draft answers: Codex for Open Source

Adapt each answer to the application form and its word limits. These answers use
the project's measured implementation; do not claim a complete production release.

## What does your project do?

RepoShield is an open-source control layer for AI-assisted software development.
It has two independent modes: deterministic review of proposed code changes, and
authorization/enforcement for connected agent actions. Verification combines
base-branch policy, dependency impact analysis and real test observations to return
PASS, BLOCK or REVIEW_REQUIRED with traceable evidence. The action gateway accepts
typed operations, binds signed expiring decisions to the requester and exact
context, consumes claims once, and runs supported work through a restricted broker.
Neither decision path depends on an LLM.

## Why is it useful?

Coding agents can change software quickly, while teams still need evidence about
what changed and limits on which actions an agent can perform. RepoShield makes
those checks explicit and inspectable. Missing mandatory test evidence cannot
become PASS; agent-controlled changes cannot authorize themselves; and a command
allowlist alone is not treated as isolation. The intended users are maintainers
and teams experimenting with connected coding agents who want reproducible,
policy-based controls.

## What have you built?

The Python prototype includes deterministic change policy and dependency analysis,
required-test evidence checks, a durable PostgreSQL job coordinator, typed action
policy, signed one-shot authorization, a separate Docker development broker,
synthetic protected-database checks, signed evidence/replay, a scoped GitHub App
Checks integration, and an authenticated server-rendered UI. The UI reads stored
results; it does not substitute mock dashboard output for verification or execution.

## How do you test it?

The full local run on 1 November 2026 reported 406 passed, 1 skipped, 0 failures
or errors in 292.72 seconds, with PostgreSQL and Docker development execution
enabled. The skipped case tested symlink report rejection; Windows did not permit
symlink creation, so that case remains unvalidated. Separate evidence includes
two signed database recovery rounds, 28 GitHub integration regressions, 36 real
Docker development execution/database checks, and live tests on a synthetic public
GitHub repository. A live head-change race made an old PASS obsolete before it
could publish success. Details and machine-readable reports are linked from
IMPLEMENTATION_STATUS.md.

## What limitations remain?

The broker and protected-database checks have run on Docker Desktop, not a dedicated
Linux host without personal-folder sharing or platform credentials. The GitHub
worker currently runs static verification; it does not supply live dynamic test
evidence. The GitHub demo PRs are synthetic and must stay unmerged. Independent
machine/operator acceptance, final bypass inspection, permanent protected backup,
and a narrated demonstration/recording remain pending. This is a submission
candidate, not a production security certification.

## How would Codex credits help?

I would use the credits to improve the existing Python project: review smaller
changes, add useful regression coverage for trust boundaries, improve operator
documentation, and make Linux isolation and install/recovery checks reproducible.
I would publish measured results and unresolved failures. Credits would not replace
tests with generated dashboard output or turn an LLM opinion into a security verdict.

## What would you work on next?

First validate the restricted broker on a dedicated Linux VM with no shared personal
folders, platform credentials or Docker socket available to execution. Then ask an
independent operator to repeat installation and the two-mode demo, close remaining
recovery and branch-protection checks, and record actual decisions and evidence.
Keep the core deterministic and preserve both verification and action-control modes.

## Repository and evidence

Repository URL: add after selecting the intended GitHub repository.

Submission archive: `reposhield-submission-candidate-20261102-v2.zip`; see its
adjacent JSON receipt for the local SHA-256. Do not upload the trusted runtime
folder, private keys, tokens, database dumps or local virtual environments.
