# Signed decisions and atomic claims (RS2 05)

RS2 05 adds Ed25519 authorization tokens and durable single-use claims. It does not
launch containers, run tests, read files or apply patches. `/actions/execute` still
returns 501. Policy ALLOW and successful claim are not completed execution evidence.
The separate [RS2 06 development broker](RESTRICTED_EXECUTION.md) now consumes
these claims and reports actual execution outcomes; dedicated-VM acceptance is pending.

The implementation uses the maintained `cryptography` package's
[Ed25519 signing and verification primitives](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/).
The validated local version is recorded in the evidence dependency lock. Existing
legacy HMAC tokens are incompatible and are never accepted by this claim API.

## Configuration and separation

Run `python -m reposhield.server.admin migrate` to upgrade to migration 0003. It adds
the authorization table; prior schemas and history remain. Generate an Ed25519 key
using trusted administrator tooling outside the source tree and all agent workspaces.
Use an unencrypted PKCS8 PEM private file protected by OS ownership/ACLs. There is no
development fallback, implicit key generation or key returned through the API.

Configure the trusted coordinator:

- `REPOSHIELD_SIGNING_KEY_FILE`: external private PEM path, used only by issuance.
- `REPOSHIELD_SIGNING_KEY_ID`: identifier such as `local-2026-01`.
- `REPOSHIELD_VERIFICATION_KEYS_FILE`: external JSON object mapping key IDs to
  standard-base64 raw 32-byte Ed25519 public keys.
- `REPOSHIELD_EXECUTOR_IDENTITIES_FILE`: separate external JSON identity list for
  trusted executors. Each record has `id`, `role: "executor"`, `tenant_id`,
  `repository_ids` and `token_sha256`, like the existing development identities.
  Executor IDs are token audiences. Their token hashes must differ from agent/user
  credentials. These credentials are for the broker, never candidate code.

Private/public key and executor-identity configuration paths inside the RepoShield
source tree or registered repositories are rejected. The administrator must protect
the external files and parent directories; path checks do not enforce Windows ACLs
or exclude every unrelated agent-readable directory. Do not mount them into a
sandbox. Only public verification keys belong on an executor. Database credentials
stay at the coordinator; a broker calls the authenticated claim API. Broker startup
must not inherit the coordinator's signing-key configuration or privileged environment.
Actual isolated broker deployment remains RS2 06.

The public verification module (`reposhield.authorization`) never loads private
keys. The coordinator-only signer is in `reposhield.server.signing`. Claims can run
after the private key file is removed; real tests verify this separation. Public
keys are reloaded on each HTTP claim, so removing a key ID rejects its tokens.
Rotate by adding the new public key, selecting the new private key/key ID for new
decisions, then removing retired verification keys. Reissuing an existing decision
returns its original token and cannot renew or rotate it; create a fresh decision.

## Execution profile binding

Extend the administrator-owned resource in ACTION_POLICY.md with `default_profile`
and `execution_profiles`. For example:

```json
{
  "default_profile": "isolated-python",
  "execution_profiles": {
    "isolated-python": {
      "image": "python@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "executor_audience": "broker",
      "timeout_seconds": 30,
      "memory_mb": 256,
      "cpu_millis": 1000,
      "pids": 32,
      "disk_mb": 64,
      "output_bytes": 65536,
      "uid": 1000,
      "network": "deny",
      "read_only_root": true
    }
  }
}
```

The digest above is illustrative, not a tested runner image. RS2 06 must build/pin
and validate the real image. RUN_TESTS selects its named profile; other actions use
the trusted default. The selected name must occur in every intersected profile
grant. Missing profiles, mutable image tags, root UID, allowed network or writable
root filesystems cannot be signed. Every image/limit change invalidates prior context.
These are signed constraints, not evidence they have been enforced at runtime.

## Wire format and API

After policy authorization (and independent approval for REVIEW_REQUIRED), the
requesting identity POSTs `/api/v1/actions/{decision_id}/token`. Other identities,
denied decisions, unresolved review and stale contexts cannot obtain tokens.
Issuance persists a single token/nonce and audit event in one transaction. Retries
return identical bytes and never extend the decision's at-most-five-minute expiry.
New policy schema fields conservatively invalidate older unsigned policy contexts;
request a new policy decision after upgrading.

The version 1 signed envelope includes algorithm and key ID. Its payload binds the
decision ID, random nonce, authenticated requester, complete version 2 action
request (including session, tenant, repository and snapshot), named resource and
profile, immutable image, limits, policy digest/epoch, session revocation epoch,
approval digest where needed, issue time and expiry. Times are integer UTC seconds.

Canonical bytes are ASCII JSON with sorted keys, no whitespace, escaped non-ASCII,
all schema defaults emitted and no floats/NaN; the signature field is excluded.
The bytes are prefixed with `RepoShield.Authorization.v1` and a zero byte for domain
separation. Signatures are canonical unpadded URL-safe base64. Unknown fields,
algorithms, versions and key IDs fail closed. Object ordering has no semantic effect.

A separately authenticated executor POSTs `/api/v1/actions/claim` with:

```text
authorization: the full signed envelope
request: the exact typed action request it intends to execute
resource_id: its resolved resource identity
profile: its complete intended execution profile
```

The claim API verifies signature, executor audience and scopes, exact requested
context, expiry, stored token identity and current policy/session/approval state.
It uses PostgreSQL locks and the unique execution-per-decision constraint to commit
one execution row plus audit event. The unique decision nonce and idempotent issuance
prevent minting a second reusable authorization for the same decision. A competing
or repeated claim returns 409. Bad signatures and mismatched execution context deny.

Successful claims return an execution ID, `state: "unknown-outcome"` and
`execution_enabled: false`. This conservative state is committed before control
could be handed to a broker. A crash or lost response therefore cannot trigger an
automatic action retry. The verification worker's lease recovery never touches
action executions. RS2 06 must add terminal evidence and reconciliation without
blind replay. Do not treat a duplicate-claim error as evidence the action completed.

Atomic consumption prevents repeated authorization claims; it does **not** prove
exactly-once external side effects. The broker can crash before, during or after
an effect. A stale snapshot/policy may also change after claim: the future broker
must enforce the bound immutable snapshot and isolation and respond to revocation.

## Validation

Run `pytest tests/test_authorization.py` with `REPOSHIELD_TEST_DATABASE_URL` pointing
to disposable PostgreSQL. Tests use real signatures and database transactions,
separate claimant processes, process exit after commit, signature/parameter tamper,
wrong audience/resources/sessions, expiry, revocation, policy/profile changes,
approval removal, rollback and HTTP credential separation. Test-only keys are
generated in an external temporary directory and cleaned up. No operational private
key is generated or committed by this implementation work.
