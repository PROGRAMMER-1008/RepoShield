# GitHub App and required check (RS2 09 local implementation)

17 October update: live operator-triggered infrastructure failure now publishes a
failed **Infrastructure failure** Check on PR #3 with authenticated evidence. A real
App-installation suspension denied fresh access, disabled an isolated binding,
prevented worker claims and prevented publication; unsuspension and explicit
onboarding restored access. The live binding is enabled. These checks did not
fabricate webhook deliveries. See [status](IMPLEMENTATION_STATUS.md) and the
`evidence/rs2-live-20261017` receipts. Suspension-webhook delivery, uninstallation,
unprocessed delayed events/publication races and actual merge-request rejection
remain distinct unvalidated cases.

For separate browser sign-in setup and a consolidated operator checklist, see
[AUTHENTICATED_UI.md](AUTHENTICATED_UI.md). Its OAuth App is separate from this
repository installation App; never put either credential in agent execution.

Live acceptance is **partial**: PASS, BLOCK and missing-test REVIEW_REQUIRED are verified; other negative cases
and full merge-gate acceptance remain pending. On 16 October 2026 the supplied
`Repoguard-demo-org/Repoguard-demo` repository and selected App installation were
verified through live GitHub calls, and a trusted bare mirror was registered.
The user confirmed working OAuth sign-in. A temporary webhook-only Cloudflare
tunnel was approved and started; the operator activated the webhook and a real
GitHub ping returned 202 OK. PR #1 subsequently completed the real docs-only
static PASS flow with a successful current-head Check and authenticated evidence.
Redelivery produced no duplicate run or Check. An expired temporary tunnel caused
an initial 502; a replacement webhook-only tunnel and original-event redelivery
restored intake. The operator then protected `main`; GitHub confirms the required
check's App ID 5339672 and enforcement level `everyone`. PR #2 then produced an
authenticated BLOCK/failed Check and GitHub reports `mergeable_state: blocked`.
No merge request was attempted; operator confirmation of the UI's precise reason
and bypass availability remains pending. The App cannot read the full administration-only
protection endpoint (403). PR #3 now proves missing mandatory auth-test evidence
stays REVIEW_REQUIRED/Check failure, with authenticated NOT_RUN evidence and GitHub
merge state blocked. See [PR #3 evidence](evidence/rs2-live-20261016/pr-3.json).
See [PR evidence](evidence/rs2-live-20261016/pr-1.json) and [implementation status](IMPLEMENTATION_STATUS.md)
for exact observations. No paid service was provisioned.

PR #1's second revision also passed with its own authenticated checkpoint and Check.
Redelivering the already-processed first-revision event after that created no new
records and did not change the current-head Check. This covers duplicate delivery
across revisions, not a first-arrival delayed event or in-flight publication race.
See [revision evidence](evidence/rs2-live-20261016/pr-1-revision-redelivery.json).

This implementation supports one explicitly configured **public GitHub.com demo
repository** and installation. Private repositories, GitHub Enterprise and merge
queues are outside this phase. GitHub requests in local regression tests are
simulated responses; PostgreSQL transactions, RSA/Ed25519 cryptography, local Git
objects, the verification worker and evidence sealing are real.

## Trusted setup when an account is available

1. Create a synthetic public demo repository with the prototype's Python project,
   tests and reviewed `.reposhield.yml` on its base branch. Do not use customer data.
2. Register a GitHub App with repository permissions **Contents: read**, **Pull
   requests: read**, **Checks: write**, and automatic metadata access. Install it on
   that repository only. Subscribe to pull-request events; retain installation and
   repository-removal events. The implementation uses a short-lived RS256 App JWT
   to request a token restricted to the configured repository and these permissions.
   [Installation authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)
   and [JWT requirements](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app).
3. Store the App RSA PEM and a random webhook secret of at least 32 characters in
   administrator-owned files outside RepoShield source and all registered agent
   repositories. Keep the existing Ed25519 evidence signer/public-key configuration
   from [AUTHENTICATED_EVIDENCE.md](AUTHENTICATED_EVIDENCE.md). These are different
   key types and purposes. No private key enters a candidate workspace or executor.
4. Create an administrator-owned **bare** mirror of the public repository and
   register its reviewed base commit using the existing `reposhield-db register`
   command. A public clone needs no installation token. Local mirror configuration
   must not be writable by agents. Do not register a personal working checkout.
5. Upgrade PostgreSQL to migration **0005** with `python -m
   reposhield.server.admin migrate`. Set `REPOSHIELD_GITHUB_APP_CONFIG_FILE` to an
   external JSON file like the following, substituting actual IDs and paths:

```json
{
  "app_id": 123,
  "installation_id": 456,
  "remote_repository_id": 789,
  "repository_id": "shop",
  "full_name": "YOUR_ACCOUNT/YOUR_PUBLIC_DEMO",
  "private_key_file": "C:/RepoShieldTrusted/github-app.pem",
  "webhook_secret_file": "C:/RepoShieldTrusted/github-webhook-secret.txt"
}
```

The numbers above are examples, not provisioned resources. Config and credentials
must all be outside source and registered repositories. Give only the trusted
coordinator/network worker access to GitHub configuration; verification and agent
execution do not need it.

6. In the trusted environment, run `python -m reposhield.server.github_worker
   --onboard`. This verifies the installation belongs to the configured App, is
   active and can obtain a repository-scoped token; it checks repository ID, name
   and public visibility before activating the database binding. Only explicit
   onboarding can reactivate a disabled installation.
7. Run the existing authenticated coordinator, the static verification worker
   (`python -m reposhield.server.process_worker`) and the separate network worker
   (`python -m reposhield.server.github_worker`). `--once` performs at most one
   intake and one publication job. The wheel also exposes `reposhield-github`.
8. Point the App webhook at an operator-provided HTTPS endpoint ending in
   `/api/v1/github/webhook`, using the same webhook secret. The current local demo
   uses a user-approved temporary webhook-only tunnel; it must be restored and its
   URL updated after expiry. The endpoint verifies the HMAC of the exact bounded
   request bytes before accepting anything. Signed ping events are acknowledged
   without scheduling. [GitHub signature validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).

## Intake, revision identity and publication

Migration 0005 adds installation bindings, webhook delivery/intake records and a
Checks publication outbox. The HTTP handler atomically records a delivery hash and
its durable pending intake intent. Duplicate IDs with identical event/body return
the existing state; changed bytes under the same ID are rejected. Raw webhook
bodies and tokens are not retained. Unknown events, including merge-group events,
cannot schedule work.

The network worker locks a pending row, gets fresh installation access and reads
the PR's **current API state**. A delayed A webhook arriving after B therefore
cannot reset the PR to A. The worker fetches only public GitHub base/PR refs into
the trusted bare mirror, without passing an installation token to Git, using a
restricted environment, disabled credential helpers/hooks, no submodule recursion
and bounded subprocess calls. Fetched refs must match the API snapshot.

The database transaction commits the intake transition, logical run, attempt/DAG,
event and publication intent together. A failure rolls that unit back. Identity
includes installation/repository/PR, trusted base tip, merge base, exact head and
execution tree. The strategy is **head-only**, not a tested merge candidate.

The remote base must equal the administrator-pinned trusted base. A changed base
stops intake; it cannot silently activate candidate policy. After reviewing and
fetching the new base into the mirror, the administrator explicitly runs:

```text
python -m reposhield.server.admin activate-base --id shop --base <reviewed-local-ref>
```

This advances the trusted policy epoch as well as the base SHA. Resolve the cause
of failed jobs before using `python -m reposhield.server.github_worker
--retry-failed`. That command resets only failed jobs for the configured active
installation; it does not change published checks or reactivate revoked access.
An already published result is not automatically re-evaluated by a policy change;
administrators must arrange a fresh verification for the active PR revision.

The publisher creates `RepoShield / verification` on the exact head with the
attempt ID as `external_id`. It reconciles existing checks by App, head and external
ID before creating one, including after a lost create response. A completed attempt
is sealed with RS2 08 and verified against its trusted checkpoint before publication.
GitHub's [Checks API](https://docs.github.com/en/rest/checks/runs) receives:

| Evidence/outcome | Conclusion |
|---|---|
| Authenticated PASS, exact current context, successful static DAG, no tests required | `success` |
| BLOCK | `failure`, with BLOCK title |
| REVIEW_REQUIRED or PASS lacking eligible mandatory evidence | `failure`, with review title |
| Infrastructure failure or cancellation | `failure`, with distinct title |
| Unfinished verification or unavailable evidence/publication | Remains pending/non-success |

No unresolved required evidence is mapped to neutral/skipped. Dynamic test PASS
publication stays closed until the deferred verification-worker/broker integration
and dedicated-host validation exist. A docs-only static change may legitimately
require no tests; signing a test-dependent NOT_RUN result never makes it success.

Publication rechecks the current PR head/base and immutable remote check identity;
a stale row is marked obsolete and cannot update a new head's check. Repository
policy activation is locked during terminal publication. GitHub is a separate
system: the PR can move immediately after a read, but any PATCH still targets only
the old immutable-head check. Required checks on the new head must remain unsatisfied.

Rows use PostgreSQL locking with `SKIP LOCKED` and bounded exponential retry delays
(five failed attempts). A crash rolls back the database claim; remote reconciliation
handles uncertain create responses. GitHub does not provide an atomic transaction
with this database: duplicate remote checks or a reconciliation limit fail closed
and require operator investigation. A lost terminal PATCH response may cause an
idempotent repeat PATCH, never execution replay. Each job requests a fresh scoped
token; tokens are never stored. HTTP redirects and non-GitHub API origins are not
accepted. API 401/403/404 conservatively disable the local installation, including
ambiguous permission/rate-limit 403 responses; 429/5xx/transport failures use retries.

Signed uninstall/suspend/repository-removal events disable the binding immediately.
New verification claims and GitHub jobs for that binding stop. An already running
static stage may finish, but the disabled publisher cannot send its result.

## Required-check setup and live acceptance still to perform

After the first real check appears, protect the demo base branch with the required
check **`RepoShield / verification`**, restricted to this GitHub App as the expected
source. Require the branch to be up to date and enforce rules without administrative
or other bypasses for the demonstration. Do not select the legacy `reposhield`
commit status. Do not enable a merge queue: merge-group validation is not implemented.
[GitHub protected-branch rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

Record real PR/check URLs, exact SHAs, App ID, rule configuration and observed
merge rejection for each non-success case. Exercise a no-tests-needed PASS, policy
BLOCK, test-dependent REVIEW_REQUIRED and a controlled infrastructure fault against
the disposable mirror. Repeat duplicate deliveries and an A/B/late-A update, then
remove installation access and verify scheduling/publication stop. Verify the base
cannot merge failure, review-required, infrastructure-error or missing/pending
checks. A displayed failure alone is not proof that branch protection enforces it.

Remaining blockers: negative demo PR scenarios and observed merge rejection. App authentication,
scoped installation access, a public bare clone and user-confirmed OAuth sign-in
have been validated on 16 October. PR #1's static PASS, evidence authentication,
Check publication and duplicate-delivery handling have been validated live.
An enforced merge gate has not. Dedicated Linux-host acceptance also remains pending.
See [the concrete operator acceptance steps](LIVE_ACCEPTANCE.md).
