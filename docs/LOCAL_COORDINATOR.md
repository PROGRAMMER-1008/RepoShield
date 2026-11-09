# PostgreSQL coordinator and worker — RS2 03

RS2 10 adds the [authenticated product UI](AUTHENTICATED_UI.md) at `/ui`. Configure
its external OAuth identity mapping to enable sign-in. Existing bearer API clients
remain separate; browser cookies do not authorize API calls. Run one coordinator
process, and omit OAuth callback query strings from any reverse-proxy access logs.

This local foundation persists real verification work. It does not enable controlled
execution. The coordinator never launches worker threads or repository code. The
separate worker performs static Git/AST/policy analysis only. Tests needing execution
produce REVIEW_REQUIRED (or BLOCK for an existing violation); they are not replaced
with synthetic passing results. Ordinary CLI verification remains available for
known local fixtures.

## Start the trusted services

Use the same interpreter for API, worker and migrations. Install `.[dev]`, or use
the exact tested versions in `evidence/rs2-03/dependencies.txt`. Python 3.10 Windows
is tested here; Python 3.12 Linux validation belongs to the execution milestone.

Set `REPOSHIELD_DB_PASSWORD` outside the repository, then:

```powershell
docker compose -f compose.rs2.yml up -d
```

The database is loopback-only on port 55432, capped at 512 MB and one CPU, with a
persistent named volume. The image is pinned to the digest actually tested. Set
`REPOSHIELD_DATABASE_URL` in trusted API/worker/admin process environments to
`postgresql+psycopg://reposhield:<URL-encoded-password>@127.0.0.1:55432/reposhield`.
Do not save credentials in source files or make these environments available to
agents. This Compose file is local development infrastructure, not isolation for
hostile repository code. No paid services or LLM API are needed.

```powershell
python -m reposhield.server.admin migrate
python -m reposhield.server.admin register --id demo --tenant local --name demo --path C:/path/to/demo-repo --base main
```

Registration is a trusted local operation. It records an absolute repository path
and resolves the trusted base to an immutable commit. The API accepts only a head
SHA for this registered repository. It cannot supply a base, filesystem path,
policy override, arbitrary URL, shell command or insecure execution flag. Registered
clones and their Git configuration must be administrator-owned; do not register an
agent-writable live checkout as a trusted clone. Static diff explicitly disables
external diff and textconv helpers. Git binaries/configuration and the installed
RepoShield code are trusted platform components.

## Configure distinct local identities

Set `REPOSHIELD_IDENTITIES_FILE` to an administrator-owned JSON file outside all
agent workspaces. The process fails at startup if this configuration is absent.
Protect its write permissions; replacing this file changes authorization. Restart
the API after an intentional identity configuration change. Each entry has:

```json
{
  "id": "local-agent",
  "tenant_id": "local",
  "role": "agent",
  "repository_ids": ["demo"],
  "token_sha256": "SHA256_HEX_OF_A_DISTINCT_RANDOM_TOKEN"
}
```

The file is an array of these entries. Generate a separate high-entropy bearer token
for each administrator, reviewer, viewer and agent identity. Store only its SHA-256
hex digest in the file; provide the original token to its authorized client outside
repository execution. IDs and token hashes must be distinct. No implicit wildcard
scope is granted, even to an administrator. SHA-256 here looks up random bearer
tokens; it is not intended for human passwords.

For example, this PowerShell creates one agent identity; repeat with independent
tokens and IDs for other roles and combine entries into the JSON array:

```powershell
$agentToken = python -c "import secrets; print(secrets.token_urlsafe(32))"
$hasher = [System.Security.Cryptography.SHA256]::Create()
$tokenDigest = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($agentToken))).Replace('-', '').ToLowerInvariant()
$hasher.Dispose()
$identity = @{id='local-agent';tenant_id='local';role='agent';repository_ids=@('demo');token_sha256=$tokenDigest}
# Serialize @($identity) into your external, protected identity file.
# Keep $agentToken in the trusted client session, not the repository or sandbox.
```

Start the processes in separate trusted terminals:

```powershell
python -m reposhield serve
python -m reposhield.server.process_worker
```

`reposhield-worker` and `reposhield-db` are equivalent installed entry points.
Start one worker on the laptop initially; two are supported by database claims.
The API can run on another trusted host sharing PostgreSQL; the registered Git
paths must exist on the worker host. It never reads those paths to execute work.

## API and lifecycle

Send `Authorization: Bearer <token>` on protected requests:

| Route | Behavior |
|---|---|
| `GET /api/v1/repositories` | Only repositories in the identity's tenant and explicit scopes |
| `POST /api/v1/repositories/{id}/runs` | `{ "head_sha": "<40 hex characters>" }`; viewer denied |
| Same route, explicit rerun | Add `"rerun": true, "request_key": "unique-client-request-id"` |
| `GET /api/v1/runs/{id}` | Logical inputs and attempt list |
| `GET /api/v1/attempts/{id}` | Persisted task states and actual final result |
| `GET /api/v1/attempts/{id}/events` | Ordered stored events; not signed evidence yet |
| `POST /api/v1/sessions` | Own session for a scoped repository, maximum one-hour TTL |
| `GET /api/v1/sessions/{id}` | Owner or scoped administrator only |
| `POST /api/v1/sessions/{id}/revoke` | Owner or scoped administrator; increments revocation epoch |
| Action authorization / approval / execution | Authentication enforced, no execution enabled; returns 501 after applicable guards |

The public health endpoint contains no run/repository data. Cross-repository and
cross-tenant IDs do not reveal run contents. Agent/viewer approval requests return
403. Session-bound authorization requests reject another owner, wrong context,
expired or revoked session. GitHub identity transport and full approval semantics
are later milestones; there is no claim of production multi-tenant readiness.

Logical identity hashes registered repository/base/policy epoch, immutable head,
implementation digest and fixed verification profile. Concurrent duplicate requests
share one logical run and initial attempt. Explicit reruns create distinct attempts;
retransmitting the same rerun key returns the same attempt. Queue insertion, tasks,
dependencies and the intake event are one transaction.

The persisted dependency chain is:

```text
snapshot -> analyze -> tests -> aggregate -> publish
```

Snapshot validates immutable Git objects without checkout. Analyze runs the existing
diff, incremental graph, policy and test-planning pipeline. Tests records NOT_RUN
or NOT_NEEDED honestly; no executor is wired in yet. Aggregate retains real evidence
and rejects missing mandatory execution evidence becoming PASS. Publish atomically
records the final result and an outbox intent. **Pending outbox rows are not GitHub
publication.** The publisher/retries for GitHub arrive in RS2 09.

Workers claim with `FOR UPDATE SKIP LOCKED`. Every claim increments its lease epoch
and retry count. Database-clock lease validity, owner, epoch and running state must
match for heartbeat, completion or failure. A live lease is not reset at startup.
Expired verification tasks retry up to three total claims with bounded exponential
delay; exhausted attempts become failed-infrastructure and descendants cancel.
Late workers cannot finalize an expired/replaced lease. Output, completion event,
attempt result and outbox intent share the publication transaction.

A crash after claim is recovered by another worker after expiry. These repeatable
verification stages can retry; action executions are not in this recovery path.
Exactly-once external effects are not claimed. An uncertain future side-effecting
action needs unknown-outcome reconciliation, not automatic replay.

## Compatibility, testing and cleanup

RS2 04 adds migration 0002 and the externally configured
[typed action policy and approval API](ACTION_POLICY.md). Run migrations again when
upgrading. Without action policy configuration, action endpoints remain unavailable;
execution stays disabled in either case.

RS2 05 adds migration 0003 and [signed authorization/atomic claims](SIGNED_AUTHORIZATION.md).
RS2 08 adds migration 0004 and [authenticated evidence/history](AUTHENTICATED_EVIDENCE.md).
Upgrade to the current migration head before starting the coordinator or worker.
RS2 09 adds migration 0005 and a separate [GitHub network worker](GITHUB_APP.md).
GitHub credentials stay in trusted external configuration; the agent runner does
not receive them. Existing installations must migrate before running the new code.
Run migrations when upgrading. Signing and claiming require explicit external key
and executor configuration; existing verification does not require an operational key.

The prior HTML/SQLite service remains available explicitly via
`python -m reposhield serve --legacy-dev-server` with the database URL unset. It is
a legacy development facility with its previous limitations, not the durable
coordinator. The new coordinator currently exposes JSON, not a replacement dashboard.
No automatic migration of old SQLite history or unsigned reports is attempted.

Run PostgreSQL acceptance tests against a disposable database by setting
`REPOSHIELD_TEST_DATABASE_URL` (separate from the application's URL):

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests/test_durable.py tests/test_static_git_boundary.py -v
```

These tests create and drop only their own random `rs_test_*` schemas. They use real
PostgreSQL locks/transactions and real worker subprocesses. Without the test URL,
PostgreSQL tests are explicitly skipped, which is not acceptance evidence. The
recorded run used PostgreSQL 17.11, not SQLite. See IMPLEMENTATION_STATUS.md.

Stop local services with `docker compose -f compose.rs2.yml down`; the named volume
is retained. Do not add `--volumes` unless you intend to delete that development
database. Keep credentials and identity configuration outside agent execution.
Retention, backups and restore rehearsal remain later release work.
