# Typed action policy (RS2 04)

This milestone evaluates actions and records bounded approvals. It does not execute
actions itself. Both product modes work without an LLM.
[RS2 05](SIGNED_AUTHORIZATION.md) adds signed decisions and atomic claims; RS2 06 must enforce immutable
snapshots, filesystem identity and Linux isolation. ALLOW alone grants no executor access.

## Trusted configuration

Run `python -m reposhield.server.admin migrate` to upgrade to revision 0002.
Existing repository/run history is retained. Existing sessions without pinned
action scope deny all actions; create a new session after configuring permissions.

Set `REPOSHIELD_ACTION_POLICY_FILE` to an administrator-owned JSON file outside
every registered repository. Protect the file and its parent directory against
agent writes using OS permissions. Resolved paths inside registered workspaces
are rejected. This does not replace OS access control or restrict an agent with
independent host access. Keep policy, tokens, platform credentials and signing keys
outside agent execution. Candidate `.reposhield.yml` cannot activate this configuration.

Example (replace the illustrative revision with a trusted snapshot identity):

```json
{
  "schema_version": 1,
  "resources": [{
    "resource_id": "demo-source",
    "tenant_id": "tenant",
    "repository_id": "repo",
    "workspace_revision": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "policy_epoch": 1,
    "administrator": {
      "actions": ["READ_FILE", "APPLY_PATCH", "RUN_TESTS"],
      "paths": ["src/app.py", "tests/test_app.py", "docs/guide.md"],
      "profiles": ["isolated-python"], "max_bytes": 65536
    },
    "repository": {
      "actions": ["READ_FILE", "APPLY_PATCH", "RUN_TESTS"],
      "paths": ["src/app.py", "tests/test_app.py", "docs/guide.md"],
      "profiles": ["isolated-python"], "max_bytes": 65536
    },
    "sessions": {
      "agent": {
        "actions": ["READ_FILE", "APPLY_PATCH", "RUN_TESTS"],
        "paths": ["src/app.py", "tests/test_app.py", "docs/guide.md"],
        "profiles": ["isolated-python"], "max_bytes": 65536
      }
    }
  }]
}
```

`sessions` keys are authenticated identity IDs. Grants are pinned at session
creation. Later configuration can narrow them but cannot enlarge an existing
session. Effective permission intersects administrator, repository and session
grants. Missing grants deny. Paths are exact portable relative names; wildcards,
absolute paths, dotfiles, traversal, Windows devices and alternate streams are
unsupported. Limits take the minimum.

The `repository` section is an administrator-activated copy of repository action
rules, never read from the candidate tree. Review trusted base rules before
activating changes. Named resource, tenant, repository, snapshot and policy epoch
come from this external file; requests cannot supply resource URLs or host paths.
The epoch must match the registered repository row. Use administrator-only database
access to update the row when activating an epoch; temporary mismatches deny.
Replace configuration atomically. No policy editing API is exposed. Invalid files
fail closed; absent configuration keeps the action feature unavailable.

The configured snapshot identity is not proof a filesystem tree matches it.
Profile names are identifiers, not working runners. Snapshot materialization,
link-safe access, image/limit binding and actual isolation belong to RS2 05–06.

## Requests and review

Create an authenticated session as described in [LOCAL_COORDINATOR.md](LOCAL_COORDINATOR.md).
POST a version 2 ActionRequest to `/api/v1/actions/authorize`, binding tenant,
repository, session and workspace revision. The typed action is:

- READ_FILE: `path` and `max_bytes` (default 65536).
- APPLY_PATCH: `patch`, limited to plain unified modifications with matching
  `--- a/path` and `+++ b/path` headers and counted `@@` hunks. Creates, deletes,
  renames, mode changes, binary patches and Git wrapper headers are unsupported.
- RUN_TESTS: nonempty `test_paths` and a named `profile`; no shell command.

DATABASE_OPERATION, NETWORK_REQUEST and EXECUTE_COMMAND return DENY. Unknown
action types and malformed contracts return HTTP 422. Additional requested
capabilities deny. Repository rules and approval cannot grant production or
unrestricted network access.

An otherwise permitted patch exclusively modifying Markdown under `docs/`
(including subdirectories) returns REVIEW_REQUIRED. Mixed documentation/code
patches deny. Other permitted source patches, reads and test requests return ALLOW.
The future executor must check existence and applicability against immutable source.

The returned `id` identifies the decision. GET `/api/v1/actions/{id}` provides its
exact request, immutable raw decision and separate approval record. Repository-scoped
reviewers/administrators can POST `/api/v1/actions/{id}/approve`. Agents, viewers
and the requesting identity cannot approve. Hard denials and plain ALLOW are not
reviewable. Approval rechecks expiry (at most five minutes or session expiry),
policy, scope, snapshot, epoch and revocation. Changed context requires a new decision.
Approval never rewrites REVIEW_REQUIRED into ALLOW.

Approval records are historical facts; the RS2 05 claim path revalidates them.
There is currently no execute path: `/api/v1/actions/execute` returns 501. Responses
explicitly include `execution_enabled: false`. Never pass these unsigned records
to the legacy command gateway, which remains development-only.

## Validation

With `REPOSHIELD_TEST_DATABASE_URL` pointing at disposable PostgreSQL:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests/test_action_policy.py tests/test_durable.py -q
```

Tests cover allowed actions, each restrictive layer, invalid paths/patches, hard
denials, self-approval, context changes, concurrent approvals, rollback, HTTP
ownership and migration preservation. These establish policy/database behavior,
not a hostile-code execution boundary.
