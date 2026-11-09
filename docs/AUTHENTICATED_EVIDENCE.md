# Authenticated evidence and history (RS2 08)

The coordinator can now seal retained verification and action-session evidence
with Ed25519 and checkpoint its identity in trusted PostgreSQL. Replay is read-only:
it verifies saved observations and never reruns a test, dispatches a command or
claims an action token. No LLM participates in these operations.

Dedicated Linux VM acceptance remains pending. On 12 October 2026 the installed
WSL distribution inventory still contained only `docker-desktop`; no `Get-VM`,
VirtualBox or libvirt command was available. The user authorized proceeding to
RS2 08 if a dedicated VM was unavailable. This work does not certify that host
boundary or complete the deferred verification-worker/broker integration.

## Setup and APIs

Run the trusted database administrator's existing migration command to upgrade to
**0004**. Earlier migration metadata stays frozen. Use the external signer and
public-key configuration from [SIGNED_AUTHORIZATION.md](SIGNED_AUTHORIZATION.md).
The same Ed25519 key may serve both functions, but evidence signatures use a
separate protocol domain and cannot be action authorizations. Private key loading
continues to reject source and registered agent-workspace locations. No key is
generated automatically or sent to the broker or candidate execution.

Authenticated routes:

| Route | Purpose |
|---|---|
| `POST /api/v1/evidence/attempt/{id}/seal` | Reviewer/administrator seals a terminal verification attempt |
| `POST /api/v1/evidence/session/{id}/seal` | Reviewer/administrator seals a point-in-time session history |
| `GET /api/v1/evidence/{checkpoint_id}` | Verify the stored bundle and return its retained artifacts/history |
| `POST /api/v1/evidence/{checkpoint_id}/verify` | Verify a supplied bundle against that trusted checkpoint |
| `POST /api/v1/evidence/{checkpoint_id}/cache-eligibility` | Supply exact desired run inputs and evaluate a cache candidate |

Seal returns `checkpoint_id` and the signed `bundle`, suitable for saving locally.
Agents and viewers cannot invoke sealing. Every operation checks repository and
tenant scope. Session access retains the owner-or-administrator restriction; being
a reviewer alone does not grant access to another identity's session. Missing keys,
missing completed results, missing history or oversized evidence fail closed.
Signing and inserting the checkpoint share one repeatable-read transaction. If
the configured verification key cannot authenticate the signature, nothing is saved.

## Authenticated contents

The canonical manifest contains a version, redaction version, exact tenant,
repository and subject identity, run ID and full immutable run inputs where
applicable, hashes of every retained artifact, event count and final linked-event
hash. Canonical JSON rejects non-finite numbers. Each event binds its index,
previous hash and full retained event. The signature covers the manifest and key ID
under the evidence-specific domain.

PostgreSQL stores an independent bundle digest, expected context, event count,
final event hash and complete signed bundle. UPDATE, DELETE and TRUNCATE triggers
reject ordinary checkpoint changes. Database owners capable of disabling triggers
remain inside the trusted administrative boundary; this does not defend against a
compromised database administrator or signing service.

The verifier independently checks signature, exact context, the entire artifact
set and hashes, event order/count/head, and the trusted bundle digest. Replacing a
result, truncating/reordering history or copying evidence across attempts, runs or
tenants fails. Even a newly signed replacement cannot satisfy an earlier checkpoint.
Historical replay reads the checkpoint snapshot, not mutable current event rows;
later session events require a new seal and cannot rewrite an older snapshot.

Verification artifacts include retained result, attempt and stage outputs. Session
artifacts include session, requests, decisions, approvals, executions and issued
authorization contexts (including exact profiles, images and limits but no reusable
authorization signatures), plus the
existing creation, decision, approval, issuance, claim, completion and revocation
events. This authenticates the retained JSON bundle. It does **not** authenticate
arbitrary old filesystem reports, legacy audit files or raw files absent from the
manifest. Those files must not be reused as authenticated evidence.

## Cache eligibility and retained data

Signature validity alone never permits reuse. Eligibility first verifies the
trusted checkpoint, then requires exact desired inputs, unchanged implementation,
trusted base and policy epoch, a completed successful fixed DAG and a PASS result
whose plan needs no tests. The independent tests stage must report NOT_NEEDED.
The existing static analyzer itself reports NOT_RUN because execution is disabled;
that does not qualify on its own. Required-test findings must be satisfied.

Dynamic test results, sessions, missing evidence and mismatched inputs cannot
qualify. The endpoint reports `reuse_enabled: false`: automatic legacy gate, graph,
parse and coverage cache reuse remains disabled. Eligible static evidence is a
checked candidate, not an automatic cache hit or a new verification PASS. Replay
without desired inputs conservatively reports no cache eligibility.

Bundles are limited to 768 KiB and 2,000 events; oversize histories are rejected,
never silently truncated into authenticated complete histories. Retained string
values are capped at 4,096 characters with an explicit marker. Known sensitive
fields, raw stdout/stderr, JUnit, patches and read-file contents are omitted from
exports; common bearer tokens, credential assignments, credentialed URLs and PEM
private keys are redacted. New durable execution outcomes use the same redacted
representation, with the existing 256 KiB input bound. Old operational records are
not rewritten, and exact action requests remain in the trusted operational tables
because authorization binds their original bytes. Redaction is best-effort for
arbitrary strings; it cannot recognize every encoded or unlabeled secret.

No log-age garbage collector or checkpoint expiry is introduced. Retain public
verification keys needed to replay historical evidence. Removing a key makes those
bundles fail verification; it never silently trusts them without a signature.

## Meaning and remaining work

An authentic record proves which retained bytes the trusted signer checkpointed.
It does not prove that candidate-authored tests told the truth, covered all behavior
or were semantically correct. Session execution state and verification verdict
remain distinct. Signing missing evidence cannot create PASS.

RS2 09 is the next backlog task: real GitHub App onboarding, webhook/outbox delivery
and required-check enforcement. Dedicated-host validation and verification-worker
integration remain open prerequisites for claims of controlled execution.
