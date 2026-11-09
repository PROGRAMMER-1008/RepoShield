# RepoShield scope and trust contract

RS2 01–02, 10 October 2026. The V2 master plan and backlog govern implementation.

RS2 03 update, 11 October 2026: the new PostgreSQL coordinator is authenticated and
does not start workers. A separate process runs static verification stages with
lease fencing and bounded retries; submitted tests/actions are not executed there.
The former SQLite/in-process service is an explicit legacy development option.
See [LOCAL_COORDINATOR.md](LOCAL_COORDINATOR.md) for identity configuration and
database/worker boundaries. Real restricted execution remains RS2 06 work.

## Two independent deterministic modes

RS2 06 development update: signed requests can now run through a separate broker
using content-addressed regular-file snapshots and bounded, network-disabled Linux
containers with no host bind mounts or socket. Real Docker Desktop tests are
development evidence; the user explicitly deferred dedicated-VM validation.
See [RESTRICTED_EXECUTION.md](RESTRICTED_EXECUTION.md). The coordinator never runs
candidate code. A separate watchdog handles container expiry after broker death;
unknown outcomes remain non-replayable and require investigation.

RS2 05 adds coordinator-only Ed25519 issuance and public-key-only validation, with
separate executor credentials and a transactional single-use claim. Claims default
to unknown-outcome and are never replayed by verification recovery. Signing keys
must stay outside source and agent workspaces. Runtime isolation and actual effects
are still absent; signatures and atomic claims do not imply exactly-once effects.
See [SIGNED_AUTHORIZATION.md](SIGNED_AUTHORIZATION.md).

RS2 04 adds deterministic intersected action policy and separate immutable approvals.
An external administrator-owned policy pins named resources and session grants;
candidate files cannot activate it. Approval is limited to permitted Markdown edits
under docs, and cannot override hard denials. Unsigned decisions are not execution
tokens. OS permissions protecting external configuration remain an administrator
obligation; path checks alone are not isolation. See [ACTION_POLICY.md](ACTION_POLICY.md).

Verification evaluates immutable Git base tip, merge base and head (execution tree is
currently head, not a synthesized merge). Its decisions are PASS, BLOCK and
REVIEW_REQUIRED. Action authorization evaluates an authenticated session and exact
typed request; its decisions are ALLOW, DENY and REVIEW_REQUIRED. Neither mode
requires an LLM. An allowed action cannot make a blocked change pass.

Execution state is separate: queued, running, completed, failed-infrastructure,
cancelled or unknown-outcome. Missing mandatory evidence cannot yield PASS.
Completion means evidence evaluation completed; it does not imply a passing verdict.

`reposhield/contracts.py` defines version 2 request/receipt contracts. Parsing an
action grants no permission and there is no new action endpoint in this milestone.
Unknown fields/versions/types are rejected. READ_FILE, APPLY_PATCH and RUN_TESTS
are the initial supported vocabulary. Network, database and arbitrary command
requests are represented for explicit denial at the future policy boundary.

## Trust boundaries

| Component | Authority and restrictions |
|---|---|
| Coordinator (trusted) | Owns identities, policy activation, approvals, platform credentials, private signing keys and durable evidence checkpoints. Reads repository policy from trusted base or administrator configuration. |
| Broker (trusted infrastructure) | Receives verification keys only; validates context and atomic claim, constructs named tasks, enforces sandbox profile. Cannot mint authorization. |
| Agent and proposed repository code (untrusted) | May request operations, edit candidate code and supply hostile outputs. Cannot activate policy, approve itself, enlarge administrator permissions or write authoritative evidence. |
| Sandbox (untrusted execution) | Disposable immutable-source copy; no platform credentials, private keys, host folders/socket or independent privileged tools; network denied and resources bounded. Tests and dependency installation are arbitrary code execution. |
| Protected resources | Outside sandbox reach; administrator-owned identities and credentials. Synthetic database integrity is checked independently by a trusted verifier. |

Effective authorization will be the intersection of administrator constraints,
trusted repository policy and authenticated session capabilities. Repository rules
can only narrow permissions. Review cannot override hard denials. Authorization
must bind exact parameters, tenant/repository/session, snapshot, policy digest and
epoch, runner image/profile, limits, audience, key ID, expiry and nonce. These are
RS2 04–06 obligations, not claims about the legacy gateway.

## Current assurance and exclusions

The existing local subprocess path is DEVELOPMENT EXECUTION for known fixtures.
Static runs are VERIFICATION ONLY. No current route qualifies as CONTROLLED
SESSION. A command allowlist is not an execution security boundary: pytest and
interpreters can perform arbitrary operations, and a connected agent retaining
independent credentials/tools can bypass a gateway.

The prototype HMAC command gateway, workspace policy/key handling, path checks and
nontransactional nonce file are legacy development facilities. Do not expose them
to untrusted agents or provide platform secrets. Production key separation,
Ed25519 and transactional consumption are RS2 04–06 work. Docker command unit
tests do not validate an actual dedicated Linux boundary. Windows host execution
does not prove network/resource isolation. The current SQLite service is a
development prototype, not the planned authenticated durable coordinator.

Version 2 fingerprints bind resolved commits, effective and raw policy, policy
provenance/errors, assurance/evidence options, runner configuration, limits,
interpreter/platform/dependencies, analyzer and implementation digest. Mutable
image tags are recorded as unresolved, never described as immutable identities.
Enforced untrusted verification requires an image digest. Future trusted service
configuration must prevent agents supplying policy overrides or insecure flags.

Gate-result reuse is disabled until RS2 08 signs manifests and verifies independent
trusted head/count checkpoints. Mutable graph/parse/coverage caches are also not
trusted by verification. Incremental graph algorithms and in-memory reuse remain.
Local reports and self-consistent audit chains are diagnostic artifacts, not
authenticated evidence: truncation/replacement cannot be ruled out without a
separate trusted checkpoint. Do not infer authenticity from a JSON checksum.

Required test semantics: every required file must have collected observations,
no failures/errors and at least one ordinary passing test. Skips, expected failures
and unexpected passes do not count as ordinary passes. Mixed passing/skipped files
may satisfy this file-level requirement; it does not require every node to pass.
Empty collection, missing reports, abnormal exit, or incomplete selected-file
evidence remains non-successful. Even a signed pytest report authenticates captured
observations, not the semantic truth of output malicious Python can forge.

No Go rewrite, LLM service, paid infrastructure, arbitrary SQL/shell execution API,
multi-tenant production claims, or optional UI features are part of RS2 01–02.
Real isolation, protected database bypass tests and actual GitHub merge enforcement
must be validated at their respective milestones before those claims are made.
