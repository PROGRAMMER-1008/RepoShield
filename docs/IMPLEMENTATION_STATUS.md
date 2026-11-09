# Implementation status

## 2 November — full regression result and consolidated submission

Follow-up virtualization inspection succeeded after approval: approximately 16 GB
RAM, a hypervisor present, VirtualBox installed at its standard Program Files path,
and no registered VirtualBox VMs. This identifies a local setup option; no guest OS
was downloaded or installed and no isolation acceptance has yet been run there.

Recovered the completed 1 November full-suite XML: **406 passed, 1 skipped,
zero failures/errors**, 292.72 seconds, 407 collected cases. PostgreSQL and Docker
development execution were enabled. The symlink-report rejection test skipped
because this Windows environment did not permit symlink creation; that case is
not claimed validated. See `evidence/final-20261101/tests.xml`.

Added SUBMISSION_START_HERE.md and an archive assembler that verifies every input
archive manifest before consolidating the preserved application candidate with
later sanitized evidence and current reviewer instructions. Previous archives stay
unchanged. This is a submission candidate, not final security acceptance.

The virtualization capability inspection was not executed: automatic approval
review failed due to a usage limit. No VM settings were changed. Independent
machine/person and dedicated Linux checks remain pending; the operator deferred
those steps. Full narrated demonstration/recording and permanent protected backup
also remain open. No paid infrastructure or optional backend rewrite was started.

## 20 October — actual operator-asset recovery rehearsal

Added and executed `benchmark/rehearse_operator_assets.py`. Backed up and restored
11 actual operator files in owner-only temporary directories inside the external
trusted folder. No credential bytes entered the repository, test executor or
submission artifacts. All restored files matched their originals before only the
restored App/UI credential references were rewritten to their restored copies.

Verified restored Ed25519 signing against the configured public verification key,
restored RSA App signing against the original public key, operator token/identity
correspondence, and App/UI configuration schema validity. Bundled and restored the
real public bare mirror, compared every ref, and passed `git fsck --full`.
Original files and mirror refs remained unchanged. Temporary secret copies were
removed. No network request or production service cutover occurred.
**Rehearsal passed**; [sanitized result](evidence/rs2-12/operator-assets-20261020/result.json).

This closes offline same-host restoration checks for these actual assets, not
encrypted/off-device backup, OAuth login from the restored configuration, database
and asset recovery at a common point in time, or whole-service recovery on another
machine. The copied runtime/launcher were compared but not activated. There is no
live executor policy/snapshot restoration claim. No persistent backup was created.
The next external steps remain independent-machine/operator checks, dedicated Linux
execution validation and narrated demo/recording. Permanent backup needs an
operator-selected protected destination. Existing release archives are unchanged.

## 18 October — two fresh technical rehearsals completed

Added `benchmark/rehearse_two_modes.py` and ran both rounds with fresh synthetic
repositories, isolated coordinator schemas and disposable protected databases.
Each round passed **13 tests, zero failures/errors/skips**: ten verification
scenarios, missing mandatory-test evidence remaining REVIEW_REQUIRED in the UI,
signed one-shot authorization/replay denial, and a real allowed patch/test action
with denied direct database access and independently unchanged protected data.
Round durations were **29.41 seconds** and **30.39 seconds**. The script fails if
any mandatory case is missing/skipped or protected-resource evidence is absent.
See [rehearsal results](evidence/rs2-12/two-modes-20261018/rehearsal.json).

These are automated two-mode technical rehearsals on Docker Desktop, not two full
narrated UI demonstrations or dedicated-host acceptance. The live verification
worker remains static-only; dynamic execution evidence here belongs to the separate
development execution workflow. No video was fabricated or claimed.

Created [operator handoff](OPERATOR_HANDOFF.md) with exact offline installation
commands/candidate hash, independent-person evidence requirements, dedicated Linux
constraints, recording steps and protected live-asset recovery requirements.
Remaining gates need the corresponding environment/operator: a separate machine,
dedicated Linux execution validation, independent operation, narrated recording,
protected live-asset recovery and independent branch-enforcement inspection.
No final release freeze or paid provisioning is claimed.

## 18 October — live publication head-change race passed

Paused a real publication immediately before its final GitHub PR read. The
operator committed to PR #1, moving head from `b9d2be4` to `0f9f6a8`.
The previously completed, genuine static PASS became `obsolete`; its remote
Check had no conclusion and never published success. Only that rehearsal-created
old-head Check was then explicitly cancelled for cleanup:
[Check 117738405148](https://github.com/Repoguard-demo-org/Repoguard-demo/runs/117738405148).
All API responses were real. The isolated audit schema and signed checkpoint
`683807785c3f439d8a1b94bce7558d22` are retained; the temporary mirror was removed.
See [race evidence](evidence/rs2-live-20261018/publication-race/result.json).

This closes the real head-change-before-final-read acceptance case. It does not
claim an atomic transaction with GitHub or validate a change after the final read;
Checks remain bound to immutable commit SHAs. The new head initially had no local
Check and GitHub reported it blocked. Requested a real operator-triggered local
intake for that new head, explicitly distinguished from a GitHub webhook delivery.
That intake completed: [Check 117739405466](https://github.com/Repoguard-demo-org/Repoguard-demo/runs/117739405466)
published authenticated static PASS on exact head `0f9f6a8`; checkpoint
`0c0be1a2c95a4902ae2c74f8cc32b3c5` authenticated independently. GitHub then
reported merge state `clean`. No merge was attempted. This README-only change
requires no tests; it does not establish dynamic test execution.
See [current-head evidence](evidence/rs2-live-20261018/publication-race/current-head-result.json).

## 18 October — current GitHub and controlled-execution acceptance

Started the existing Docker Desktop runtime and RepoShield database after the
session restart, preserving its volume. Initial validation processes were stopped
while the database was unavailable; successful retry evidence is reported below.
Restored the existing local coordinator and workers with the external launcher.

Added `benchmark/live_stale_event_check.py`. It retrieves a historical GitHub
payload and operator-re-signs it into a fresh local intake schema. Its first local
arrival selected the actual current API head, rather than the old event head.
A genuine historical-head publication became obsolete before remote Check
creation. No GitHub branches or Checks were modified by this rehearsal; its
temporary mirror/schema were cleaned up. This is not a new GitHub-origin delivery
through the public relay. [Evidence](evidence/rs2-live-20261018/stale-first-arrival-retry/result.json).

Current regression: **28 GitHub integration tests passed in 33.02 seconds** with
one dependency deprecation warning. HTTP transport is simulated in that suite;
it is separate from the real API rehearsal. Current real Docker development
execution: **36 tests passed in 54.02 seconds**, including protected synthetic
database equality and restricted execution, with the same warning. No skipped
case is included in these counts. Dedicated Linux acceptance remains pending.
See [GitHub tests](evidence/rs2-live-20261018/github-regression.xml) and
[execution tests](evidence/rs2-local-20261018/tests.xml).

Added `benchmark/live_publication_race_check.py` for an operator-coordinated real
head change before the final publication read. It uses a real completed static
PASS and real GitHub responses, with a bounded operator pause. Its live result
must be recorded separately before claiming this gate passed.

The [final acceptance checklist](FINAL_ACCEPTANCE_CHECKLIST.md) distinguishes
remaining fresh-machine, dedicated-host, independent-operator, live asset recovery,
merge/bypass and timed-demo/recording gates. No final freeze or full-suite rerun
is claimed. The v4-ui archive is unchanged; these new scripts/evidence are outside
that preserved candidate.

## 17 October — installed UI release candidate

Built a separate UI candidate from a clean source copy, excluding cached bytecode.
All 91 Python source files match the wheel byte-for-byte. The original v3 archive,
wheel and lock remain unchanged. Installed all 37 hash-locked wheels offline into
a new Windows Python 3.10 virtual environment without system site packages;
`pip check` passed and imported RepoShield was verified inside that environment.

Packaged checks initially produced 211 passes and one failure: a UI boundary test
assumed its temporary directory was inside the source installation. An intermediate
rerun confirmed that moving it under the test working directory was insufficient.
The test now explicitly places forbidden configuration under each actual protected
root: the registered repository and installed package. The 503 rejection and
bearer-login denial assertions remain unchanged. The complete UI suite then passed
**34 tests in 16.47 seconds**, with one dependency deprecation warning. Combined
with **179 passing non-UI cases**, this covers 213 distinct passing cases across
verification, graph/selection, portability, required evidence/cache integrity,
action policy, authorization and UI. This is not a full-suite rerun.

Two signed recovery rounds against this installed wheel passed: six real
PASS/BLOCK/REVIEW_REQUIRED outcomes authenticated after restore and restart;
wrong keys were rejected and table contents remained equal. Temporary keys and
the disposable database container were removed. Evidence and initial failures are
retained in [candidate validation](evidence/rs2-12/ui-candidate/clean-install.json).

Candidate: `.rs2-release/reposhield-offline-windows-py310-20261017-v4-ui.zip`.
It retains development version 0.2.1; use its archive/hash receipt for identity.
Same-host clean-environment validation is complete; RS2 12 is not frozen.
Next: close delayed first-arrival/in-flight GitHub event acceptance and rehearse
the complete timed demo. Dedicated Linux/fresh-machine, independent operator,
actual merge rejection, live asset recovery and fallback recording remain pending.

## 17 October — product UI redesign

Implemented a new responsive visual system in `reposhield/server/product_theme.py`
and applied it to the existing server-rendered `product_ui.py`: navy navigation,
branded sign-in, repository cards, readable decision badges, verification stage
cards, audit timelines, prominent findings and expandable stored evidence.
Repository counts and records remain scoped database queries; no synthetic
dashboard metrics or execution outcomes were added. Authentication, CSRF,
authorization, escaping/redaction and the restrictive CSP remain in place.
Keyboard focus, skip navigation and reduced-motion styles are included.

Validation: **33 product UI tests passed, 1 dependency deprecation warning, in
18.86 seconds**, using isolated PostgreSQL test schemas. GitHub HTTP in that suite
is simulated at its explicit upstream boundary; this is not new live OAuth
acceptance. No existing assertions were weakened. An initial run caught the word
PASS in unconfigured-page marketing copy; the copy was corrected and the full UI
suite rerun. See [test results](evidence/ui-redesign-20261017/final-tests.xml).
Desktop repository/verification screens and a 390px mobile verification view were
visually inspected using sanitized test-generated previews. The actual coordinator
was restarted with the new source; its live sign-in page rendered successfully at
`http://127.0.0.1:8080/ui`. Existing browser sessions may require sign-in again.
See [live screenshot](evidence/ui-redesign-20261017/live-login.jpg) and
[verification screenshot](evidence/ui-redesign-20261017/verification-desktop.jpg).

No full backend-suite rerun or new live signed verification is claimed for this UI
change. Python source changes affect implementation provenance; previous signed
results remain historical evidence. The existing v3 offline archive predates this
UI and has not been relabeled or overwritten. **Next task:** rebuild a separately
identified release candidate with this UI and repeat installed-wheel validation.
RS2 12 remains in progress. Dedicated Linux/fresh-machine isolation, independent
operator validation, live operator-asset recovery, delayed first-arrival/in-flight
GitHub races, actual merge rejection and final demo/freeze remain pending.

## 17 October — live infrastructure failure and installation revocation

Completed two more RS2 09 acceptance checks using the real GitHub App/API and an
isolated PostgreSQL schema (`rs_live_fault_0522abdd3db24093986429bc63587c43`, retained
for signed-checkpoint auditing). The live mirror and previous verification records
were preserved. These were explicitly operator-triggered jobs, not webhook claims.

For PR #3, a disposable public bare mirror was made unavailable to the real worker.
After three actual GitError failures the attempt became `failed-infrastructure`,
with no result; dependent stages were cancelled. Only retry waiting was accelerated.
After restoring the disposable path, the real publisher created
[Check 117382557634](https://github.com/Repoguard-demo-org/Repoguard-demo/runs/117382557634)
with failure and **Infrastructure failure** title. Checkpoint
`339c7346ce6e462ba4815b81256be174` authenticated. GitHub reports PR #3 blocked.
See [failure evidence](evidence/rs2-live-20261017/infrastructure-01/result.json).

Then suspended the real selected App installation through its JWT-authenticated
GitHub API, with restoration in a finally block. Fresh installation access was
denied. A queued publication in the isolated schema detected `installation_inactive`
and disabled its binding; a worker claim returned no job and no remote Check was
created. Unsuspended the installation and explicitly onboarded isolated and live
bindings. Cancelled the unexecuted synthetic queue and marked its unpublished Check
obsolete. [Revocation evidence](evidence/rs2-live-20261017/revocation.json) records
the actual suspension/access denial/claim denial/restoration. A final independent
read confirmed the installation active and live binding enabled; see
[restored state](evidence/rs2-live-20261017/restored-state.json).

This closes live API-detected suspension denial/recovery and infrastructure-failure
publication. It does not prove delivery of a suspension webhook, uninstallation,
previously unprocessed delayed events, in-flight publication races, or an actual
rejected merge request. PRs remain unmerged. No backend/test implementation was
changed and no full-suite rerun is claimed. Remaining external acceptance includes
dedicated Linux/fresh-machine and independent operator checks; release freeze is
still withheld.

## 17 October — signed recovery acceptance

Extended the installed-wheel rehearsal with optional `--signed-evidence` mode.
Two clean disposable database rounds produced real static PASS/BLOCK/REVIEW_REQUIRED,
sealed all six outcomes with ephemeral external Ed25519 keys, backed up/restored
PostgreSQL, and authenticated every restored checkpoint with public-key-only replay.
All six authenticated again after database restart. Wrong public keys returned 409
in both rounds; the restored private key signed a verified challenge and restored
content-addressed snapshot bytes matched. Public-table hashes remained identical.

Evidence: [signed recovery](evidence/rs2-12/rehearsal-signed-recovery/rehearsal.json).
Temporary external keys/snapshots and the disposable container/volume were removed.
No live credentials, live tables or candidate backend source were changed. The
existing clean-environment package was used; no dependency or full-suite rerun was
needed for this opt-in reproduction-script change.

**Synthetic signed-evidence/key/snapshot recovery is now validated.** Live operator
asset backup/restore, independent-machine operation and dedicated Linux isolation
are distinct pending checks. RS2 12 remains in progress, not frozen. The next
independent work is remaining live GitHub adverse/revocation validation; account
actions and a dedicated host may still require the operator. No release-ready or
production disaster-recovery claim is made.

## 17 October — offline clean-environment release validation

Acquired 36 dependency wheels plus the built RepoShield wheel and recorded their
SHA-256 values in `requirements-release-windows-py310.lock` and
[wheel manifest](evidence/rs2-12/offline-wheels.json). Installed all 37 into a fresh
venv using **--no-index --require-hashes**, without system-site-packages. Sandbox
DNS blocked initial acquisition; the authorized network retry succeeded. No paid
service was used. `pip check` passed and all installed versions match the manifest.

Copied unchanged tests into a separate directory without a source package. The
installed wheel passed **39 tests in 52.06 seconds** across end-to-end verification,
policy selection, AST graph and portability suites. Package origin was separately
verified in isolated Python mode. This is selected packaged-code regression, not
a full-suite rerun. The full 405/1/1 result remains historical.

Repeated both disposable PostgreSQL recovery rounds with the new environment:
each produced real static PASS/BLOCK/REVIEW_REQUIRED and identical public-table
contents after restore and restart. Cleanup removed the temporary container.
See [clean-install receipt](evidence/rs2-12/clean-install.json),
[JUnit](evidence/rs2-12/clean-tests.xml), and
[recovery](evidence/rs2-12/rehearsal-clean-env/rehearsal.json).

The candidate packager now optionally includes the exact offline wheelhouse and
hash lock, rejecting changed/missing/extra wheels against the acquired manifest.
The updated release guide provides offline installation commands. This validates
a **fresh environment on the same Windows host**, not a fresh machine or Linux.
Python, Git, Docker and the pinned PostgreSQL image remain external prerequisites.
Next: trusted-asset/signed-evidence recovery and remaining live GitHub acceptance;
dedicated Linux isolation, independent operation and final release freeze remain pending.

Updated 16 October 2026. Scope: RS2 01–10 local implementation and RS2 11 local evaluation/report work; live App authentication, user-confirmed OAuth sign-in, and real PR PASS/BLOCK/REVIEW_REQUIRED flows now work. Dedicated-host acceptance for 06–07 and remaining live negative/merge-enforcement acceptance for 09 remain pending. Authoritative documents:
REPOSHIELD_MASTER_PLAN.md, BUILD_TASKS_V2.md, COST_ESTIMATE.md and CODEX_BUILD_BRIEF.md.
Superseded plans were not used as implementation requirements.

**RS2 01–05 are complete. RS2 06 is in progress: development execution is implemented;
dedicated Linux VM acceptance remains pending. RS2 07's protected database
development demonstration is implemented; its dedicated-host acceptance is also pending.
RS2 08 authenticated evidence/history is implemented under the user's explicit
instruction to proceed if no dedicated VM was available.**

**RS2 09's local GitHub App integration is implemented. On 16 October the supplied
public demo repository, App private key, selected installation and scoped token
were verified against GitHub. PR #1 now has an authenticated static PASS and live
GitHub Check; duplicate delivery produced no duplicate run/check. PR #2 has an
authenticated BLOCK and GitHub reports its merge state blocked. Remaining negative
cases and full merge-enforcement acceptance remain pending; see below.**

**RS2 10's local authenticated UI is implemented. On 16 October the user confirmed
successful GitHub sign-in and the repository list after an OAuth client-ID typo
was corrected. Independent multi-user review and deployed HTTPS acceptance remain
pending. See the RS2 10 section and live setup update for validation limits.**

## 16 October — live GitHub and local operator setup

Connected `Repoguard-demo-org/Repoguard-demo` (repository 1421513676), organization
343277690, operator `PROGRAMMER-1008` (149040824), App 5339672 and installation
171934598. The installation is selected-repository scope with Contents read,
Pull requests read, Checks write and Metadata read. These were checked against
the real GitHub API using the supplied RSA PEM; token values were never printed
or retained. All 29 uploaded baseline files match the local demo after newline
normalization. Trusted base: `07f22c74f0b9e42c715adef1573b767339e99e02`.

Backed up and corrected external configuration paths, `proofguard-demo` versus
`repoguard-demo` scope, and the OAuth client ID. The final ID begins with capital
`O`: `Ov23ct1Yb90mjiKFl6tM`. The prior digit-zero ID returned 404 from GitHub.
After correction, a deliberately invalid-code diagnostic returned the expected
`bad_verification_code`; the user then confirmed real sign-in and repository access.

Trusted runtime files, credentials, Ed25519 signer and public keys, logs, launcher
and bare mirror reside under `C:/Users/pjpra/Desktop/RepoShieldTrusted`, outside
source and the candidate mirror. A persistent local PostgreSQL container
`reposhield-live-demo-db` uses the cached pinned PostgreSQL 17 image, named volume
`reposhield_live_demo_pg`, 512 MiB/one CPU, and loopback port 55432. Coordinator
port 8080 and separate verification/GitHub workers are running for this demo.
No agent executor was enabled and no paid resource was provisioned.

An authenticated **no-change baseline** run completed all five stored stages with
PASS, and its signed evidence replay authenticated. This is a local smoke check,
not a PR or required-check acceptance result. Anonymous repository access returned
401. See [non-secret live evidence](evidence/rs2-live-20261016/setup.json). The
previous 405-test suite remains the last full regression result; this configuration
work did not change backend source and is not claimed as another full suite run.

The user approved a temporary Cloudflare tunnel for a webhook-only loopback relay.
Relay checks reject UI/API routes (404), unsigned webhook requests with valid
delivery metadata (401), and oversized bodies (413). The operator activated the
App webhook and saved its Pull request subscription after the previously absent
webhook API returned 404. A **real GitHub ping**, delivery `3848550244899880960`,
was accepted with **202 OK**. PR #1 subsequently exposed an expired tunnel: its
original delivery returned 502 and created no run. Restarted the approved tunnel,
verified public UI/repository routes still return 404, updated the existing App's
webhook URL through its API, and redelivered the original GitHub event (202).
Stopped only the expired tunnel process. The current temporary endpoint is
`https://hart-reaches-personality-exec.trycloudflare.com/api/v1/github/webhook`.
It depends on the laptop/relay/tunnel staying online and can change after restart.

### Live PR #1 acceptance evidence

[PR #1](https://github.com/Repoguard-demo-org/Repoguard-demo/pull/1), head
`45be28ba87af7b0e186915b0d87da6f38605cd20`, changes only README.md. The real webhook
was processed into attempt `aa789bc261844595a280d6cf9e8ac503`; the worker published
[Check 116893314396](https://github.com/Repoguard-demo-org/Repoguard-demo/runs/116893314396)
as completed/success with title **PASS: authenticated static verification; no tests
required**. Checkpoint `bd5a7568b2e140aeabeff317ba91a4e7` replay returned
`authenticated: true`. This verifies the static docs-only path, not dynamic tests.

A second real redelivery returned 202 with the same delivery GUID. The database
still contained one PR delivery/attempt association and one published Check row;
GitHub still showed one Check for that head. Recorded selected non-secret API and
database observations in [pr-1.json](evidence/rs2-live-20261016/pr-1.json).
No backend/test source changed and the full regression suite was not rerun.

The operator subsequently saved branch protection. GitHub's branch endpoint now
reports `protected: true`, required context `RepoShield / verification`, App ID
5339672 and enforcement level `everyone`. PR #1 remains open with a successful
Check and `mergeable_state: clean`. The full protection endpoint returns 403 with
the intentionally limited App token, so strict/up-to-date and other detailed
settings remain operator-reported rather than independently inspected. See
[branch-protection.json](evidence/rs2-live-20261016/branch-protection.json).
The forbidden-path PR now returns BLOCK and GitHub reports its merge state blocked
(see below). The next live acceptance step is missing mandatory test evidence.
Reordered commits and installation revocation
also remain unvalidated live. RS2 09 is not fully accepted; dedicated Linux VM,
multi-user review and deployed HTTPS UI limitations remain unchanged. RS2 11 is
the next implementation phase after these acceptance gaps are addressed or deferred.

### Live PR #2 forbidden-path evidence

[PR #2](https://github.com/Repoguard-demo-org/Repoguard-demo/pull/2) adds only the
harmless text file `.github/workflows/reposhield-denied.txt`. At head
`991f198e773d7b2f702086e9f56e04bbaf433765`, the live webhook was processed into
attempt `a211bc0b538146ccae41046802e6dc8c`. Published
[Check 116898667750](https://github.com/Repoguard-demo-org/Repoguard-demo/runs/116898667750)
completed with failure and title **BLOCK: policy or verification failed**.
Checkpoint `18bc4fa94f87483e842eea40d68a01aa` authenticated on replay.

GitHub reports `mergeable: true` (no merge conflict) but `mergeable_state: blocked`,
while the PR remains open and unmerged. This is an observed blocked merge state,
not a performed merge API rejection. Operator confirmation of the precise UI
reason and unavailable bypass is pending. See [pr-2.json](evidence/rs2-live-20261016/pr-2.json).
No source/test changes or new full regression run were required for this live check.

### Live PR #3 missing mandatory test evidence

[PR #3](https://github.com/Repoguard-demo-org/Repoguard-demo/pull/3) modifies only
`auth/login.py`, head `b4bd389de34956fdc49c00e6609adc29db60b800`. Attempt
`c132b9a446374f96a0309c35d7ab770a` published
[Check 116900036606](https://github.com/Repoguard-demo-org/Repoguard-demo/runs/116900036606)
with conclusion failure and title **REVIEW_REQUIRED: unresolved evidence or review**.
Checkpoint `ad03a2a734ea49c9bf01a1e501b3c0f2` authenticated. Its result selects
`tests/auth/test_login.py` and `tests/auth/test_tokens.py`, records `NOT_RUN`, and
reports that required tests were not executed. The missing evidence did not become
PASS; cache eligibility is false. GitHub reports merge state `blocked` without a
merge conflict. No merge was attempted and the PR remains open.

Selected observations are retained in [pr-3.json](evidence/rs2-live-20261016/pr-3.json).
The operator's PR #2 reply confirmed its BLOCK title, but did not explicitly confirm
bypass availability; that limitation remains. Next live check: update PR #1's head
and redeliver its old event. Infrastructure failure, revocation/recovery and full
merge-rejection acceptance remain pending. No backend/test edits or full suite rerun.

### Live PR #1 revision and old-event redelivery

The operator advanced PR #1 to `b9d2be4edc01f778855b5f8baa17a2f5d7abe6c1` with a
second README-only change. The real synchronize event created attempt
`715c7055f61a4c58a64c350af76cc068` and successful
[Check 116901120580](https://github.com/Repoguard-demo-org/Repoguard-demo/runs/116901120580).
Checkpoint `ea529b61cb2a4ea796e86a9c24bda65c` authenticated. GitHub reports the PR's
new head as clean; the original Check remains associated with the original SHA.

Redelivered the original PR-open event through GitHub. Redelivery
`3848595863792254976` returned 202 with its original GUID. Before/after comparisons
confirmed the two existing delivery records and two revision-specific Check records
were unchanged; the new head still had exactly one successful Check with the same
ID. See [before](evidence/rs2-live-20261016/pr-1-revision-before-redelivery.json) and
[after](evidence/rs2-live-20261016/pr-1-revision-redelivery.json) observations.

This is live **already-processed old-event deduplication after a new revision**.
It does not validate a previously unprocessed delayed old event or an in-flight
stale publication race; those remain live acceptance gaps. Next acceptance work:
a controlled infrastructure-failure case, remaining event-ordering cases and
installation revocation/recovery. No backend changes, full suite rerun or merge
attempt occurred in this check.

## RS2 11 — local evaluation and submission material

Proceeded under the user's instruction to keep working on the next RS task while
external acceptance remains incomplete. Added independent benchmark tools without
editing backend implementation or existing tests:

- `benchmark/evaluate_v2.py`: preserves ten original demo cases, adds ten authored
  change fixtures, saves exact patches/raw results/Git objects and environment;
  measures fifteen typed policy cases and three seeded incremental/full graphs.
- `benchmark/selection_v2.py`: independently executes full and safe-selected tests
  on fresh copies of twelve authored mutations; retains JUnit, process results,
  mutation inputs, selected paths and timings. No arbitrary repository input.
- `benchmark/test_overhead.py`: opt-in real PostgreSQL benchmarks using existing
  test fixtures and disposable schemas; external ephemeral keys, actual Ed25519
  issuance/atomic claims and replay rejection. No executor or live-table changes.

Actual results: final `run-02` matched **20/20 change verdicts, 15/15 policy cases**,
and **3/3 graph edge-set comparisons**. Full and selected suites each detected
**12/12 mutations**; selected 34 versus 108 test-file selections. Full process time
totaled 19.011 seconds, selected 17.371 seconds (8.6% reduction). This one ordered
synthetic run is not a general performance claim. No misses in this corpus;
no statistical flake study was performed.

Twenty real scheduler enqueue/initial-claim cycles and twenty signed action
authorize/issue/claim cycles passed; every replay returned 409. Benchmark pytest
result: **2 passed, 1 warning in 7.32 seconds**. The first invocation had two setup
errors from a missing fixture import, corrected before rerunning. Initial policy
measurements warned about an unvalidated benchmark override; request construction
now validates all fields, and the final complete rerun emitted no such warning.
All three new modules compile. No existing assertion was weakened.

Evidence: [metrics](evidence/rs2-11/metrics.json),
[final scenario summary](evidence/rs2-11/run-02/summary.json),
[mutation runs](evidence/rs2-11/selection-01/results.json),
[scheduler](evidence/rs2-11/overhead-01/scheduler.json), and
[authorization](evidence/rs2-11/overhead-01/authorization.json).
The scenario summary's pending list describes measurements outside that individual
runner; the separate selection/overhead outputs above complete those local measurements.
The prior full suite remains 405 passed/1 skipped/1 warning, not rerun this turn.

Created [EVALUATION_REPORT.md](EVALUATION_REPORT.md) with methodology, raw inputs,
algorithm/architecture references, measured timings and explicit limitations, plus
[OPERATOR_GUIDE.md](OPERATOR_GUIDE.md) consolidating setup, live demo, restart and
submission operation. Existing threat-model, signed-authorization, execution and
database demonstration documents remain the detailed technical references.

**RS2 11 local measurement/report work is implemented, not full submission acceptance.**
Fixture tests use the development subprocess backend and policy cases do not prove
isolation. Dedicated VM, complete live GitHub adverse/revocation tests, independent
reviewer/HTTPS checks and another-person operation remain pending. Next: close the
remaining acceptance gaps and begin RS2 12 packaging/restart/backup-restore rehearsal;
do not claim a release freeze or fresh-machine validation yet.

## RS2 12 — candidate packaging and local recovery rehearsal

Built `reposhield-0.2.1-py3-none-any.whl` without downloading dependencies. The
161,917-byte wheel SHA-256 is
`1c1690deacac95a04ce066e2dfa069ac8399a69e509d573dc8b562a4e08e3cf6`.
Its packaged Python files match workspace source; migrations and the demo policy
are present. No private-key/runtime-config filenames were found in its members.
Installed it into `.rs2-release/installed` without dependencies; rehearsal explicitly
checks imports come from that target. `pip check` passed for the existing environment.
Windows sandbox temporary-file rename failures required elevated local build/install;
these were filesystem permission errors, not package validation successes.

Added `requirements-release-windows-py310.txt` with tested dependency versions.
This is not a portable hash lock or a downloaded offline dependency wheelhouse.
Added `benchmark/rehearse_release.py`: creates only a randomly named disposable
PostgreSQL container, uses fresh databases, invokes installed-wheel migrations and
real static workers, dumps/restores, checks every public table's row count/content
hash, restarts the container, and compares again. No live config/credentials are read.

**Two rounds passed** in `rehearsal-03`: each produced real PASS, BLOCK and
REVIEW_REQUIRED; restore and restart equality passed for every table. The disposable
container and anonymous volume were removed. Initial attempts on random Docker
ports failed host connection and cleaned up; explicit loopback port 55434 worked.
Host TCP readiness is now checked before migration. No firewall or live demo
database changes were made. Evidence: [wheel](evidence/rs2-12/wheel.json) and
[recovery](evidence/rs2-12/rehearsal-03/rehearsal.json).

Added explicit-allowlist candidate packaging with manifest/hash/CRC verification,
and [RELEASE_REHEARSAL.md](RELEASE_REHEARSAL.md) covering reproduction, scope,
eight-minute demonstration sequence, exclusions and release gates. No fallback
video exists yet. No existing tests/backend code changed; the full suite was not
rerun and its 405/1/1 result remains historical.

**RS2 12 remains in progress.** These are same-host installed-package/static-worker
and synthetic database recovery checks, not two complete fresh-machine product demos.
External policy/keys, snapshots, signed-evidence replay after restore and live service
recovery need further rehearsal. Dedicated Linux acceptance and the remaining live
GitHub adverse/revocation/merge checks still block release claims. Next: clean
dependency installation, complete trusted-asset recovery, and close those acceptance
gaps before freeze or submission-ready labeling.

## RS2 01 — baseline and scope contract

Completed repository inspection and baseline reproduction. No applicable AGENTS.md
was found in the workspace or ancestor directories. The project root has no `.git`;
`git status --short` reports “not a git repository.” Nested Git directories are
generated demo/test repositories, not source-control history for this project.
No repository was initialized and no commit/diff against an earlier revision can
be claimed. Existing prototype, demo branches and user files were preserved.

Before edits, Python source/tests and pyproject.toml were backed up locally in
`.rs2-original.zip`; their SHA-256 inventory is
[source-before.json](evidence/rs2-01-02/source-before.json). The original ten demo
scenarios and their expected decisions remain unchanged.

Created a clean `.venv-rs2` without system site packages. Interpreter: CPython
3.10.11 on Windows; Git 2.52.0.windows.1. Exact installed dependencies are in
[dependencies.txt](evidence/rs2-01-02/dependencies.txt), and interpreter/platform
details in [environment.json](evidence/rs2-01-02/environment.json). Python 3.12 Linux
compatibility remains unvalidated. No services, infrastructure or billable APIs
were provisioned. Package downloads required approval after sandbox DNS failed.

The two-mode scope, exclusions, trusted coordinator/broker, agent, sandbox,
protected resources and credential boundaries are recorded in
[THREAT_MODEL.md](THREAT_MODEL.md). Versioned Pydantic contracts distinguish
verification decisions, action requests/decisions and execution states. These
contracts do not authorize or execute actions. The legacy command adapter remains
version 1 development compatibility; it rejects version 2 and unsupported types.

## RS2 02 — verification integrity

Implemented:

- Required files need at least one ordinary passing test and no failed/error
  observations. All-skipped, all-xfailed, XPASS-only, missing and empty collection
  cannot satisfy the requirement. A mixed pass/skip file may satisfy this explicit
  file-level requirement. Setup/teardown failures are retained by the pytest plugin.
- PENDING is now non-successful. Missing mandatory evidence cannot be made
  informational through low severity or `on_fail: info`. Selected files missing
  from observations and abnormal pytest exits cannot silently pass.
- Result schema version 2 and validated receipt metadata distinguish verdict from
  execution state. Request schema version 2 rejects unknown fields/types/versions.
- Fingerprints include resolved base/merge-base/head/execution tree, repository,
  raw/effective policy and provenance/errors, assurance/evidence options,
  runner/image identity, limits, isolation/environment policy, runtime/dependencies
  and implementation digest. Inherited environment values are hashed, not disclosed.
  Mutable image tags are explicitly unresolved; enforced Docker execution requires
  a digest. Proposed untrusted head policy no longer configures its own runner.
- Gate-cache reuse is disabled until authenticated persistence in RS2 08. The
  verifier also ignores mutable disk graph, parse and coverage caches that could
  otherwise suppress findings or prune evidence. Incremental graph algorithms and
  in-memory parse reuse remain; balanced selection conservatively falls back to safe.
- Equivalent inputs keep a logical run ID but every invocation has a unique attempt
  directory. `force` remains compatible; both values create fresh attempts. No prior
  attempt is deleted or overwritten. Repeated/concurrent verification is covered.

Existing tests asserting cache reuse were updated to assert the intentionally
stricter contract: stable logical identity, fresh evidence, distinct attempts and
preserved prior output. No scenario verdict or failure assertion was relaxed.

## RS2 03 — durable database and worker foundation

Added a versioned PostgreSQL migration for repositories, logical runs, attempts,
fixed-stage tasks/dependencies, sessions, action requests, decisions, executions,
events and outbox. Intake is transactional and deduplicates immutable logical
inputs; explicit rerun keys create separate attempts. Trusted base, policy epoch
and implementation identity are bound to the run. Repository registration is a
local administrator command, not an agent API.

The separate worker process claims tasks with PostgreSQL row locks, renewable
leases and monotonically increasing fencing epochs. Expired owners cannot finish
or resurrect a lease. Restart recovery and bounded retries apply to verification
work; exhausted attempts fail with descendants cancelled. Completion, events and
publication intent commit atomically. No Redis or hosted services were added.

The authenticated coordinator requires distinct externally configured identities,
tenant/repository scopes and roles. Session ownership, expiry and revocation guard
action requests. Anonymous actions and approvals are rejected; agents cannot
approve. Action policy and execution endpoints remain explicitly unavailable
until their scheduled milestones. The API starts no verification worker thread.
The old SQLite UI requires `--legacy-dev-server` at the CLI.

Workers currently perform real static verification only. They do not run candidate
tests or commands; mandatory test evidence is NOT_RUN and cannot produce PASS.
Git diff disables external diff and text conversion helpers. This foundation does
not claim that a command allowlist or a separate process is an execution sandbox.
See [local setup and operation](LOCAL_COORDINATOR.md).

Before RS2 03 edits, source was backed up in `.rs2-03-original.zip` and hashed in
[source-before.json](evidence/rs2-03/source-before.json). Existing tests were not
weakened in this phase. The 26 added regression cases exercise real PostgreSQL,
including independent worker processes racing to finalize one lease, process
crash/restart recovery, heartbeat expiry, transactional rollback, bounded failure,
duplicate/rerun identity, roles/session checks and Git helper suppression.

### RS2 03 actual validation

- Full suite: **179 passed, 1 skipped, 1 warning in 134.08 seconds**.
  [Full log](evidence/rs2-03/full-suite.txt). The skip remains Windows symlink
  permission; the warning remains Starlette's deprecated AnyIO alias.
- Focused PostgreSQL and Git regressions: **26 passed, 1 warning in 20.93 seconds**.
  [Focused log](evidence/rs2-03/postgres-focused.txt).
- Real migration upgrade and integration-test downgrade/re-upgrade succeeded.
  Offline migration SQL also generated successfully: [SQL](evidence/rs2-03/migration.sql).
- Dependency consistency and Python compilation passed. Exact versions:
  [dependencies](evidence/rs2-03/dependencies.txt),
  [dependency check](evidence/rs2-03/dependency-check.txt).
- Wheel build succeeded in a separate build venv; packaged migration modules and
  console entry points were checked. [Build log](evidence/rs2-03/package-build-final.txt),
  [wheel inspection](evidence/rs2-03/wheel-check.txt). The initial build attempt
  failed because the host build tooling was too old; its log is retained.

Validation used Python 3.10.11 on Windows and a real local PostgreSQL 17.11 container
limited to 512 MB and one CPU, with loopback-only port 55432. Package downloads,
Docker startup and local database access used approved escalation. No paid service
or billable API was enabled. The disposable database used synthetic credentials.
Tests used isolated schemas and no customer data. After validation, the disposable
`reposhield-rs203-db` container was stopped successfully and removed by its `--rm`
setting; the downloaded image remains cached. No other containers were changed.
[Source change inventory](evidence/rs2-03/source-changes.json) records this phase's
changes; no pre-existing tests or demo Python source were modified.

Full-suite command (outside the command sandbox, with the disposable database URL
in `REPOSHIELD_TEST_DATABASE_URL` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`):

```powershell
.venv-rs2/Scripts/python -u -m pytest -q -ra --basetemp=.test-rs2-03-full
```

Without the test database URL, PostgreSQL tests skip; such a run is not RS2 03
acceptance evidence. Follow LOCAL_COORDINATOR.md to reproduce the local database.

## RS2 04 — typed action policy and approval

Implemented a pure deterministic evaluator for READ_FILE, APPLY_PATCH and RUN_TESTS.
Administrator, trusted repository and pinned session grants intersect; current
configuration can narrow but not enlarge an existing session. Named resources and
snapshot/policy context come from external administrator-owned configuration.
Missing scopes deny. Production database, arbitrary command and unrestricted
network requests explicitly deny. No candidate policy activation endpoint exists.

Paths use exact portable relative identities. Unsupported path spellings and patch
formats deny. Patches are limited to counted unified modifications; only permitted
Markdown modifications under `docs/` require review. Hard denials cannot be approved.
Reviewers must be repository-scoped and distinct from the requester; agents/viewers
cannot approve. Approval rechecks expiry, revocation, snapshot, policy and session
scope. Concurrent approvals produce one row/event and preserve the raw decision.

Migration 0002 adds session scopes and approvals without changing frozen migration
0001. Decisions, request payloads and audit events commit atomically. Authenticated
HTTP routes authorize, expose the exact request for review and record approval.
No execution route was enabled, no keys were generated and no billable API was used.
Setup and supported formats are documented in [ACTION_POLICY.md](ACTION_POLICY.md).

Source backup: `.rs2-04-original.zip`;
[before hashes](evidence/rs2-04/source-before.json),
[change inventory](evidence/rs2-04/source-changes.json). Existing tests and demo
source were not modified. New regressions include positive read/patch/test policy
and HTTP flows, all three restrictive layers, forbidden actions/paths, malformed
patches, concurrent review, expiry/context changes, self-approval, transaction
rollback and migration data preservation.

Initial existing-foundation run: **25 passed, 1 warning in 21.68 seconds**
([log](evidence/rs2-04/existing-foundation.txt)). New tests initially failed collection
because of an incorrect fixture-module import; no product behavior was validated
by that failed run. After correcting the import: **36 passed, 1 warning in 6.45 seconds**
([focused log](evidence/rs2-04/policy-focused-02.txt)). Four additional integration
tests were then added before the full-suite run.

Final full suite: **219 passed, 1 skipped, 1 warning in 138.48 seconds**.
[Full log](evidence/rs2-04/full-suite.txt). This includes all 40 new action-policy
regressions, with real PostgreSQL transactions and HTTP API calls. The Windows
symlink-permission skip and upstream Starlette/AnyIO warning remain unchanged.
No pre-existing tests were weakened. Command, using the same Python 3.10.11 venv,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and a real `REPOSHIELD_TEST_DATABASE_URL`:

```powershell
.venv-rs2/Scripts/python -u -m pytest -q -ra --basetemp=.test-rs204-full
```

The test database ran locally with synthetic credentials, loopback-only port
55432, 512 MB RAM and one CPU. After validation, `reposhield-rs204-db` was stopped
successfully and removed by its `--rm` setting. No other containers were changed.
No external dependency blocks this milestone.

Offline migration SQL, compilation, dependency consistency and wheel build passed.
The wheel includes the new policy modules and migration 0002.
[Migration SQL](evidence/rs2-04/migration.sql),
[dependency check](evidence/rs2-04/dependency-check.txt),
[build log](evidence/rs2-04/package-build.txt),
[wheel inspection](evidence/rs2-04/wheel-check.txt).

## RS2 05 — signed decision and atomic claim

Implemented version 1 canonical, domain-separated Ed25519 authorization envelopes
using `cryptography` 47.0.0. Tokens bind requester, complete typed request,
tenant/repository/session/snapshot, resource, profile/image/limits, policy context
and epoch, revocation epoch, independent approval, executor audience, key ID,
nonce and expiry. Unknown schema/algorithm/key and altered fields fail closed.

The coordinator-only signer loads an explicitly configured external private PEM;
there is no fallback or automatic operational key generation. The verifier and
claim adapter require public keys only. Paths inside source/registered workspaces
are rejected. Distinct executor credentials guard the claim endpoint; agent/user
credentials cannot claim. OS protection of external files remains an administrator
responsibility, and no actual sandbox deployment is claimed.

Migration 0003 adds durable signed tokens. Issuance, nonce and event commit together;
repeated issuance returns the identical token without renewed expiry. Claims
revalidate current policy/session/approval and exact intended execution context,
then atomically insert one execution row/event. Locks plus unique execution per
decision serialize replay. Committed claims start as unknown-outcome and are never
replayed by verification recovery. No command, patch, read or test executes here.

Source backup: `.rs2-05-original.zip`;
[before hashes](evidence/rs2-05/source-before.json),
[change inventory](evidence/rs2-05/source-changes.json). No existing tests or demo
source were modified. Setup, canonical wire format, rotation and the distinction
between single-use claims and exactly-once effects are in
[SIGNED_AUTHORIZATION.md](SIGNED_AUTHORIZATION.md).

Initial focused validation: **85 passed, 1 warning in 20.27 seconds**
([log](evidence/rs2-05/focused.txt)), including the 40 prior policy tests. Additional
tests then added independent-process replay, process crash immediately after claim,
HTTP executor separation, concurrent issuance, missing/unsafe profiles, approval
removal, wrong public key and issuance rollback.

Final full suite: **277 passed, 1 skipped, 1 warning in 159.06 seconds**.
[Full log](evidence/rs2-05/full-suite.txt). All 58 added tests passed, including real
Ed25519 signatures, PostgreSQL concurrency, two independent claimant processes with
exactly one winner, and a process exiting immediately after commit. Restart finds
one unknown-outcome execution and rejects replay. The existing Windows symlink skip
and upstream Starlette/AnyIO warning are unchanged. No existing tests were weakened.
Command, with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and the disposable PostgreSQL URL in
`REPOSHIELD_TEST_DATABASE_URL`, outside the command sandbox:

```powershell
.venv-rs2/Scripts/python -u -m pytest -q -ra --basetemp=.test-rs205-full
```

Python compilation, dependency checks, offline SQL generation and wheel build passed.
The wheel includes the signer/verifier, claim adapter and migration 0003.
[Dependencies](evidence/rs2-05/dependencies.txt),
[dependency check](evidence/rs2-05/dependency-check.txt),
[migration SQL](evidence/rs2-05/migration.sql),
[build log](evidence/rs2-05/package-build.txt),
[wheel inspection](evidence/rs2-05/wheel-check.txt).

Test-only signing keys were generated in external temporary directories and removed
by fixture cleanup; no operational private key was generated or committed. Tests
use synthetic credentials and local PostgreSQL limited to 512 MB and one CPU.
Package installation and local database access used approved escalation. No paid
infrastructure or billable APIs were enabled.
The disposable `reposhield-rs205-db` container was stopped successfully after
validation and removed by its `--rm` setting. No other containers were changed.

## RS2 06 — restricted execution development implementation

The host had only Docker Desktop's WSL distribution, initially stopped. The user
explicitly selected: “Use Docker Desktop for development; report VM validation as
pending.” No dedicated Linux execution VM was supplied or provisioned. Docker
Desktop was started for bounded synthetic development tests, not represented as
the plan's hardened host boundary.

Implemented a separate broker with public-key verification, exact resource mapping,
real coordinator claims and executor-scoped status/result endpoints. Read actions
use immutable content-addressed snapshots. Patches check exact old bytes/positions
and produce new snapshots while preserving originals. Test actions stream regular
file data to a fresh container with no source/output bind mount, host socket,
platform credentials or private key. Snapshot identity and bounds are verified.

The real Linux runner enforces non-root, read-only root, dropped capabilities,
seccomp, no-new-privileges, no network, memory/swap/CPU/PID caps, bounded workspace
tmpfs and output, plus timeout removal. Current authority is polled without blocking
the wall timer; revoked/stale sessions cancel. Container cleanup is in finally;
an independent watchdog handles expiry if the broker process dies. Claim state
remains unknown-outcome after a crash and cannot be replayed. Terminal reports are
scoped, immutable and distinct from verification verdicts.

Candidate dependencies are prepared inside the same sandbox using snapshot-supplied
wheels, no-index/no-deps pip, no network and an isolated target. Missing dependencies,
all-skipped/empty/failed tests and missing observations cannot satisfy mandatory
evidence. Test observations remain potentially forgeable by malicious test code.
The existing verification worker is still static-only pending integration with a
validated execution host; no mocked results or dashboard substitutes were introduced.

A registry DNS failure blocked `docker pull python:3.12-slim` even outside the
command sandbox. Independent work continued using cached base image
`sha256:bbeddfa2510a08c7da0abc6a76a46d0a4be44642f78ea7a752ef0d39b09e20f0`
(Python 3.12.15, pytest 9.1.1). Restricted builds ran with network none and no
candidate build scripts. [Final build log](evidence/rs2-06/image-build-final.txt),
[local image ID](evidence/rs2-06/image-id.txt). Image identity means the inspected
local Docker ID, not an invented remote registry digest.

Source backup `.rs2-06-original.zip` covers Python, tests and pyproject.toml.
The runner Dockerfile was initially replaced while adding the new recipe, then the
restricted recipe was moved to Dockerfile.restricted. The legacy Dockerfile's
PIP_PACKAGES and /workspace behavior was reconstructed from the cached image's
actual build history; its prior comments/bytes were not backed up and are not
claimed unchanged. No pre-existing Python tests were modified or weakened.

Initial actual validation:

- Real runner/snapshot suite: **20 passed in 22.84 seconds**
  ([log](evidence/rs2-06/runner-focused.txt)). Includes in-container uid/capability/
  seccomp/network/root checks, actual disk/PID exhaustion, memory/output/timeout
  failures, cleanup and unchanged original snapshot.
- Real HTTP/PostgreSQL/broker suite: **4 passed, 1 warning in 9.83 seconds**
  ([log](evidence/rs2-06/broker-focused.txt)). Includes a separate broker process
  running a real container and denying replay.
- First full suite: **302 passed, 1 skipped, 1 warning in 176.64 seconds**
  ([log](evidence/rs2-06/full-suite.txt)). Offline dependency preparation and additional
  hardening were added afterward.
- Offline dependency regressions: **3 passed, 19 deselected in 6.49 seconds**
  ([log](evidence/rs2-06/dependencies-focused.txt)). Includes missing-module evidence.
- Full suite after offline preparation: **304 passed, 1 skipped, 1 warning in
  176.59 seconds** ([log](evidence/rs2-06/full-suite-final.txt)).
- Full suite including independent watchdog crash cleanup: **305 passed, 1 skipped,
  1 warning in 181.15 seconds** ([log](evidence/rs2-06/verified-suite.txt)).

Final review found that JUnit alone does not distinguish XPASS from ordinary pass.
A trusted pytest observer is now loaded before candidate import paths and records
ordinary passes and all phase failures. Both bounded observer data and XML must
satisfy the requested-file evidence rule. Added explicit all-XFAIL and XPASS-only
negative regressions; neither can satisfy mandatory evidence. This is still an
observation channel, not an unforgeable oracle against malicious test code.

Compilation, dependency consistency and wheel build passed; the wheel includes the
broker entry point, runner/watchdog adapters, snapshot store and lifecycle adapter.
[Dependency check](evidence/rs2-06/dependency-check.txt),
[build log](evidence/rs2-06/package-build.txt),
[wheel check](evidence/rs2-06/wheel-check.txt),
[source inventory](evidence/rs2-06/source-changes.json).

Final full suite, after all source/image changes: **307 passed, 1 skipped, 1 warning
in 182.46 seconds** ([final log](evidence/rs2-06/final-observer-suite.txt)). This
includes all 30 new cases, real containers, real PostgreSQL, a separate broker
process over local HTTP, live revocation and independent watchdog cleanup after
process death. The sole skip is the existing Windows symlink permission test;
the upstream Starlette/AnyIO warning is unchanged. No existing tests were weakened.
The final saved [isolation observations](evidence/rs2-06/real-isolation.json) identify
the actual image and Docker HostConfig used by the positive probe.

Command (outside the command sandbox), with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`,
the disposable `REPOSHIELD_TEST_DATABASE_URL`, `REPOSHIELD_TEST_RUNNER_IMAGE` set
from the recorded image ID, and `REPOSHIELD_TEST_EVIDENCE_DIR=docs/evidence/rs2-06`:

```powershell
.venv-rs2/Scripts/python -u -m pytest -q -ra --basetemp=.test-rs206-final-observer
```

Setup, current bounds, watchdog deployment and remaining acceptance requirements:
[RESTRICTED_EXECUTION.md](RESTRICTED_EXECUTION.md). RS2 06 is not marked complete.
No services were purchased, paid infrastructure provisioned or billable APIs enabled.
After final validation, no labelled runner containers remained. The disposable
`reposhield-rs206-db` was stopped successfully and removed by its `--rm` setting.
The restricted image remains cached for reproduction; unrelated containers and
images were not changed. [Environment](evidence/rs2-06/docker-environment.txt),
[PostgreSQL version](evidence/rs2-06/postgres-version.txt),
[remaining runner containers](evidence/rs2-06/remaining-runner-containers.txt).

## RS2 01–02 actual validation (historical)

Historical planning result: 111 passed / one skipped in 61.21 seconds. This was
not treated as current evidence.

Clean baseline, before implementation edits: **111 passed, 1 skipped, 1 warning
in 53.38 seconds**. [Full baseline log](evidence/rs2-01-02/baseline-unrestricted.txt).
The skip is Windows symlink creation permission; the warning is Starlette's use of
a deprecated AnyIO alias. Two earlier command-sandbox attempts were interrupted after a local
Git clone failure / stalled doctor check. Their partial output is preserved in
[baseline.txt](evidence/rs2-01-02/baseline.txt); they are not counted as passing runs.
The successful run used the same clean venv outside the command sandbox.

Before-fix reproductions: all-skipped required tests returned PASS; a BLOCK result
edited to PASS was reused despite only the independent audit chain being checked.
See [reproductions-before.txt](evidence/rs2-01-02/reproductions-before.txt). The
modified demo result artifact was restored immediately afterward. Focused negative
regressions produced **10 failed, 2 passed** before the fixes, recorded in
[regressions-before.txt](evidence/rs2-01-02/regressions-before.txt).

Initial post-change focused run: 31 passed, 2 failed. Both positive fixture failures
were caused by pytest discovering the parent project's root rather than the fixture
root. The fixture invocation now explicitly sets `--rootdir=.` and its test file;
expected outcomes are unchanged. [Initial focused log](evidence/rs2-01-02/focused.txt).

First full post-change run: **150 passed, 1 failed, 1 skipped in 112.23 seconds**.
All ten scenario verdicts matched. The failure was a portability assertion looking
for `runs/<run>/report.html` rather than `runs/<run>/<attempt>/report.html`. The
updated assertion requires reports for every attempt and validates all ten showcase
links. [First full log](evidence/rs2-01-02/full-suite.txt).

Second full run: **152 passed, 1 skipped, 1 warning in 113.39 seconds**.
[Full log](evidence/rs2-01-02/full-suite-final.txt). Final review then added explicit
environment-policy fingerprint binding and a regression; final validation follows.

Final full-suite validation: **153 passed, 1 skipped, 1 warning in 116.67 seconds**.
Command: `.venv-rs2/Scripts/python -u -m pytest -q -ra --basetemp=.test-rs2-verified`
with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, outside the command sandbox.
[Final log](evidence/rs2-01-02/verified-suite.txt). This includes 42 new regression
cases and all ten unchanged demo scenario verdicts. The one skip and upstream
warning are the same as the clean baseline.

After that run, the analysis-cache regression was strengthened to inject valid,
correctly versioned graph/parse records with false dependency data, rather than
malformed cache records. Its isolated run initially found a fixture directory
setup dependency (missing `parents=True`); after fixing fixture setup it passed:
**1 passed, 41 deselected**. Command: `pytest tests/test_rs2_integrity.py -q -k
unsigned_analysis_cache --basetemp=.test-rs2-cache-poison-02` using the same venv.
[Isolated result](evidence/rs2-01-02/cache-poison-final.txt). No production source
changed after the final full-suite run. [Source change inventory](evidence/rs2-01-02/source-changes.json)
also confirms demo source files are byte-for-byte unchanged.

`.venv-rs2/Scripts/python -m pip check`: **No broken requirements found.**
[Dependency check](evidence/rs2-01-02/dependency-check.txt).
`.venv-rs2/Scripts/python -m compileall -q reposhield tests`: exit 0.

Reproduction commands (PowerShell, project root):

```powershell
python -m venv .venv-rs2
.venv-rs2/Scripts/python -m pip install -r docs/evidence/rs2-01-02/dependencies.txt
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.venv-rs2/Scripts/python -u -m pytest -v -ra --basetemp=.test-rs2-reproduce
```

Use a fresh basetemp name to preserve earlier artifacts. Parent plugin autoload is
disabled for repeatability; the sandbox explicitly loads RepoShield's pytest plugin.

## RS2 07 — protected synthetic database development demonstration

Implemented a separate disposable PostgreSQL shop database with independently
generated owner and SELECT-only verifier credentials. No credentials, signing
keys or host mounts enter candidate execution. The fixture contains only synthetic
products, customers and orders (two rows each). The trusted verifier reads all
three tables in a read-only repeatable-read transaction, bounds row counts, and
records table existence, counts and canonical content hashes without retaining
row contents or credentials.

The real-service demonstration exercises explicit DATABASE_OPERATION denial and
refused token issuance with no execution; an allowed application patch followed
by actual signed broker/container tests; bounded direct TCP connection attempts;
and a trusted external before/after database comparison. A bridge-network control
first reaches the exact protected database IP/port, while the network-none sandbox
cannot. Separately, the live database rejects an incorrect password and the
SELECT-only verifier cannot DELETE. These distinguish policy, network and database
privilege enforcement. Nothing depends on an LLM or fabricated dashboard data.

Regressions detect same-count content changes, deleted rows, excessive rows,
missing tables, empty/missing evidence and internally inconsistent digests.
The new focused suite passed **11 tests, 1 warning in 15.25 seconds**. During
development, the first run found Docker's endpoint nested under Networks/bridge;
the next found the new test expected 403 where the established issuer returns
409 for denied decisions. Endpoint discovery and that exact contract assertion
were corrected; no existing test or authorization behavior was changed.

The [reproduction guide](PROTECTED_DATABASE_DEMO.md) describes the opt-in fixture,
controls and limits. [Actual demonstration evidence](evidence/rs2-07/protected-database.json)
records matching before/after hashes, actual execution IDs and container settings.
The evidence is unsigned until RS2 08. The source was backed up before edits to
`.rs2-07-original.zip`, including Python, tests, runner, docs and pyproject.toml.
The repository still has no root Git history. No dependencies were added; no paid
services were provisioned.

Final full regression: **318 passed, 1 skipped, 1 warning in 232.60 seconds**.
Command: `.venv-rs2/Scripts/python -u -m pytest -q -ra --basetemp=.test-rs207-full`,
with the real PostgreSQL, runner-image and protected-database opt-in variables from
the reproduction guide. [Full output](evidence/rs2-07/full-suite.txt). This includes
all 307 previously passing tests and 11 new cases. The only skip is the existing
Windows symlink-permission test; the warning is the existing Starlette/AnyIO
deprecation. `pip check` reports no broken requirements; `compileall -q reposhield
tests` exits 0. [Source comparison](evidence/rs2-07/source-changes.json) confirms
that the only source/test changes are the three new files; existing Python, tests,
runner files and pyproject.toml match the pre-edit backup.
The disposable coordinator database was stopped and removed after validation;
no restricted execution or protected-demo containers remained. Cached images and
unrelated Docker resources were retained.

## RS2 08 — authenticated retained evidence and history

Rechecked local Linux availability: WSL listed only `docker-desktop`; no `Get-VM`,
VirtualBox or libvirt command was installed/available. There is no provisioned
dedicated host available for acceptance. The user explicitly authorized proceeding
to RS2 08 in that case. No VM was purchased or provisioned, and RS2 06–07 acceptance
has not been silently promoted to complete.

Added a public-key-only evidence verifier, coordinator-only domain-separated
Ed25519 signing, and migration 0004 for immutable PostgreSQL checkpoints. Canonical
manifests bind exact subject/run/tenant/repository/context, retained artifact hashes,
event count and final event head. Checkpoints additionally bind the whole signed
bundle. UPDATE, DELETE and TRUNCATE are rejected for ordinary checkpoint operations.
Private keys remain external to source and agent execution.

Scoped sealing, replay, supplied-bundle verification and cache-eligibility APIs now
support terminal attempts and point-in-time session histories. Agent/viewer identities
cannot seal. Replay reconstructs retained results and session/decision/approval/
execution events without scheduling or executing anything. Signatures alone do not
qualify a cache candidate: exact inputs, current implementation/base/policy epoch,
a successful fixed DAG and explicit no-tests-needed evidence are also required.
Dynamic/missing test evidence cannot qualify. Automatic cache reuse stays disabled;
old unsigned filesystem results and analysis caches remain untrusted.

New durable execution outcomes and exported bundles omit raw logs/JUnit/patch/read
contents and known secret fields. Strings are redacted and capped; bundle size and
event count are bounded, with excessive histories rejected instead of silently
truncated. Exact operational action requests are retained inside trusted PostgreSQL
for authorization; old operational records are not rewritten. There is no log-age
garbage collector. [Protocol, API, retention and trust details](AUTHENTICATED_EVIDENCE.md).

Regression coverage includes result/artifact replacement, truncated/reordered/
modified events, wrong run/attempt/tenant/context, absent or removed keys, signature
failure, a valid re-signature that conflicts with an existing checkpoint, checkpoint
mutation, scope/role controls, read-only replay, log redaction and missing evidence.
A real static worker result is sealed and replayed; separate synthetic persisted
records test integrity without pretending to be real execution outcomes.

The initial run exposed shared migration metadata creating the new table too early;
schema 0004 now owns separate metadata, preserving frozen earlier migrations. A
positive cache test also caught the existing static analyzer's NOT_RUN status for
a NONE plan. Eligibility now checks the independent tests stage's NOT_NEEDED status,
successful stages and exact context, preserving mandatory-evidence requirements.
The focused evidence/coordinator suite passed 49 tests, 1 warning in 34.17 seconds
before the final additional regressions. Full-suite results are recorded below.

Full suite: **344 passed, 1 skipped, 1 warning in 236.01 seconds** using real
PostgreSQL, Docker Desktop and the protected-database opt-in. Command:
`.venv-rs2/Scripts/python -u -m pytest -q -ra --tb=short --basetemp=.test-rs208-full`.
[Full output](evidence/rs2-08/full-suite.txt). The skip is the existing Windows
symlink-permission case; the warning is the existing Starlette/AnyIO deprecation.
This includes all 318 previously passing cases and 26 RS2 08 cases.

After that full run, session replay was extended to include the issued public
authorization payload (exact image/profile/limits/revision) without exporting its
reusable signature. All evidence regressions were rerun against the final code:
**26 passed, 1 warning in 15.68 seconds**. [Final focused output](evidence/rs2-08/final-evidence-suite.txt).
The full suite was not repeated after that isolated refinement. The final wheel
was rebuilt and its new modules/migration matched source byte-for-byte.
[Build output](evidence/rs2-08/package-build.txt), [wheel check](evidence/rs2-08/wheel-check.txt).
[Source comparison](evidence/rs2-08/source-changes.json) confirms all existing tests,
runner files and dependency configuration remain unchanged.

The disposable RS2 08 coordinator database was stopped and removed. No restricted
runner or protected-demo containers remained; cached images and unrelated Docker
resources were retained.

Source, tests, runner and docs were backed up to `.rs2-08-original.zip` before edits.
No existing tests were weakened or edited. No dependencies or paid services were
added. `pip check` and compilation succeeded; the wheel build succeeded (setuptools
reported existing demo package-directory discovery warnings).

## RS2 09 — GitHub App integration, local implementation

Read the authoritative backlog/master plan and current code before editing; no
applicable repository AGENTS.md was found. Preserved Python and the explicitly
legacy development service. Source, tests, runner, docs and packaging configuration
were backed up to `.rs2-09-original.zip`. No existing tests were edited or weakened.

Added external GitHub App configuration, real RS256 JWT creation, repository-scoped
installation token acquisition, installation/repository identity and public-visibility
checks, bounded HTTP responses and redirect refusal. Tokens are ephemeral and not
persisted or forwarded to Git/candidate execution. One public GitHub.com repository
and installation are supported; private/GHES/merge-queue workflows are not claimed.

Migration 0005 adds installation bindings, webhook delivery/intake rows and a
durable Checks publication outbox. The bounded webhook route checks the exact-body
HMAC, deduplicates delivery IDs, rejects changed-content reuse and persists pending
intake atomically. A separate trusted network worker fetches current PR API state
and public refs; its transaction commits delivery processing, run/DAG and publication
intent together. Logical inputs bind base tip, merge base, head, execution tree,
installation and remote repository/PR. Delayed A events cannot overwrite current B.

The publisher reconciles checks by App/head/attempt external ID, seals and verifies
RS2 08 evidence, checks current PR/base and trusted policy, and maps only eligible
static PASS to success. BLOCK, unresolved REVIEW_REQUIRED, missing mandatory test
evidence, cancellation and infrastructure failures remain non-success. Current
dynamic execution integration is still unavailable; test-dependent PASS publication
is closed. Check updates target only the exact immutable old head even if the PR
moves after a current-head read. No neutral/skipped bypass is used.

Publication and intake have bounded retries and PostgreSQL row locking. Lost check
creation responses are reconciled; ambiguous duplicate remote checks fail closed.
Uninstall/suspend/removal disables new remote verification claims and publication.
Trusted CLI operations explicitly onboard/reactivate access, approve a changed base
with policy-epoch advance, and retry failed jobs after correcting their cause.

Local tests use **simulated GitHub HTTP responses**, clearly separated from real
PostgreSQL, RSA/Ed25519 verification, Git objects, static worker runs and signed
evidence. The first focused run passed 43 tests, 1 warning in 39.71 seconds; the
expanded run passed **50 tests, 1 warning in 46.69 seconds** before the final ping
and administration cases. [Focused output](evidence/rs2-09/focused.txt).
No live API, public fetch, PR/check or enforced merge-gate validation is claimed.

Final full regression: **372 passed, 1 skipped, 1 warning in 254.01 seconds**,
including all 344 previous passing cases and 28 new GitHub cases. Command:
`.venv-rs2/Scripts/python -u -m pytest -q -ra --tb=short --basetemp=.test-rs209-full`,
with real PostgreSQL, restricted-image and protected-database opt-in variables.
[Full output](evidence/rs2-09/full-suite.txt). The one skip remains Windows symlink
permission; the warning remains Starlette's deprecated AnyIO alias. No source was
changed after this run.

`pip check`: no broken requirements. `compileall -q reposhield tests`: exit 0.
The wheel build succeeded, and all five new modules/migration matched source bytes;
the `reposhield-github` entry point is present. [Build output](evidence/rs2-09/package-build.txt),
[wheel check](evidence/rs2-09/wheel-check.txt). Existing setuptools demo-directory
discovery warnings remain; no new dependency was installed.
The disposable RS2 09 database was stopped and removed. No restricted runner or
protected-demo containers remained; cached images and unrelated resources were retained.

See [GITHUB_APP.md](GITHUB_APP.md) for configuration, operational semantics, official
GitHub documentation links, branch-protection setup and live acceptance procedure.
No App, repository, hosting, tunnel, paid infrastructure or billable API was enabled.
No Python dependency was added. [Source comparison](evidence/rs2-09/source-changes.json)
records changes; existing tests and runner files match the backup.

## RS2 10 — authenticated product UI

Preserved Python and the existing HTML styling; no React/dependency migration.
The PostgreSQL coordinator now serves `/ui`: scoped repositories, run attempts
with real stored findings/stages and audit, controlled sessions/actions with
separate immutable decision/approval/execution, and read-only policy/settings.
Empty, in-progress (manual reload), unavailable storage and authorization error
states are explicit. Views do not manufacture a PASS or execute repository code.
Lists show up to 100 recent records; older records remain in trusted storage.

Added GitHub.com OAuth authorization-code sign-in with S256 PKCE, single-use
state bound to the initiating browser, numeric user and organization checks, and
an external administrator-owned tenant/role/repository mapping. Active organization
membership alone grants no role. Login config and secret paths are rejected inside
source or registered workspaces, including resolved links. HttpOnly SameSite cookies
are Secure with a `__Host-` prefix on HTTPS; explicit HTTP is limited to loopback
development. User access tokens are transient during login, not stored in browser
storage or login sessions. Browser cookies cannot authenticate machine APIs.
Packaged coordinator access logging is disabled to avoid OAuth query-code logging.

Same-origin forms require per-session CSRF values. Exact-request approval also
submits the displayed action digest and uses the existing transactional service:
no self-approval, DENY override, stale policy/snapshot, expired or revoked session.
The UI refuses approval when the entire patch cannot be displayed without redaction
or truncation. Viewer cannot mutate; only an administrator can revoke via the UI.
Changing repository/attempt/session/action IDs cannot evade tenant/repository scope.
Stored raw process logs, reusable authorizations, credential files and private paths
are not rendered. Text is escaped; retained summaries use existing bounded redaction.

The coordinator uses bounded process-local browser state: 256 pending logins for
five minutes and 1,024 browser sessions for 15 minutes. Restart loses all sessions;
configuration changes invalidate them. This intentionally supports one coordinator,
not distributed login sessions. GitHub membership is checked at login; organization
removal alone may take up to 15 minutes to expire local access. Remove the local
grant or restart for immediate browser revocation. HTTPS proxy deployment, live
OAuth and live GitHub required checks are not validated. Generic redaction cannot
identify every possible unstructured secret; raw logs stay omitted.

Before source edits, `.rs2-10-original.zip` preserved source/tests/runner/docs and
pyproject.toml. This root still has no Git history. Baseline was rerun against real
PostgreSQL, the cached restricted Docker image and protected-database fixture:
**372 passed, 1 skipped, 1 warning in 269.12 seconds**. New focused UI suite:
**33 passed, 1 warning in 15.98 seconds**. Initial unprivileged focused run could
not connect to localhost PostgreSQL (Windows permission error); rerunning with
approved local network access resolved this, without changing assertions.

The UI tests exercise real PostgreSQL and the real static worker, including a
docs-only PASS and test-dependent NOT_RUN/REVIEW_REQUIRED. GitHub HTTP responses
are simulated: these are not live OAuth results. One action-view test deliberately
inserts an unknown-outcome execution record to check rendering; actual broker
execution remains covered by the existing Docker integration suite, not that UI
fixture. Sanitized HTML snapshots in `evidence/rs2-10/preview` were inspected in the
in-app browser for repository, action and verification layout. Their CSRF fields
are removed and their links/forms are inert without the application; they are
visual test artifacts, not an operating dashboard or authentication demonstration.

Final full suite: **405 passed, 1 skipped, 1 warning in 295.51 seconds**. The skip
is the existing Windows symlink-permission test; the warning is the existing
Starlette/AnyIO deprecation. This run includes actual Docker broker and synthetic
protected-database tests, not just UI fixtures. [Full output](evidence/rs2-10/full-suite.txt),
[focused output](evidence/rs2-10/ui-tests.txt), and [commands/environment](evidence/rs2-10/checks.md)
are retained. Dependency validation and bytecode compilation pass; wheel build
succeeds with the existing demo-data packaging warnings. The wheel's five updated
runtime modules match source bytes. Backup comparison confirms all existing tests
and runner Python files unchanged, no Python source deleted, three runtime files
modified, two runtime modules and one test module added. See
[source comparison](evidence/rs2-10/source-changes.json) and
[wheel check](evidence/rs2-10/wheel-check.json).

The temporary preview server and disposable `reposhield-rs210-db` container were
stopped after checks. No paid resources, GitHub credentials, new subscriptions or
billable APIs were enabled.

Operator instructions, exact OAuth callback, permissions and safe credential paths
are in [AUTHENTICATED_UI.md](AUTHENTICATED_UI.md). Repository App setup remains in
[GITHUB_APP.md](GITHUB_APP.md).

## Limitations and next task

The next task is to finish **RS2 06 dedicated Linux host acceptance**, then connect
the verification worker to that validated broker. The exact external blocker is
the absence of a dedicated VM without personal-host integration/shared folders or
platform credentials; the user explicitly deferred this. The runnable image and
Desktop development tests are implemented, but do not close that acceptance item.
Validate independently supervised watchdog operation and daemon/reboot recovery on
the dedicated host, then repeat the RS2 07 database demonstration there. The local
RS2 07 development work is complete, but neither RS2 06 nor RS2 07 is fully accepted.
The user authorized RS2 08 while that environment work remains pending; authenticated
evidence/history is now implemented. RS2 09's independent local work is also done.
**Next: finish RS2 09 live PR/check and merge-enforcement acceptance.** The App,
installation, credentials, public repository, local runtime, user-confirmed
OAuth sign-in and real webhook intake now work. PR #1's docs-only PASS,
authenticated evidence and duplicate-delivery handling were validated live.
The App-bound required check is now visible in GitHub's protected-branch summary;
negative PR scenarios and actual merge rejection remain pending. The next independent
implementation phase was **RS2 11 evaluation and submission material**; its local
20 change/15 policy scenarios, mutation runs, service timings and documentation
are now implemented above. Next is remaining acceptance and RS2 12 rehearsal.
This work retains the outstanding 06–07 and 09–10
acceptance gaps; no controlled deployment or merge-enforcement claim is permitted
until those actual validations succeed.

Raw action ALLOW is a policy result; separately issued signed tokens can now be
claimed once, but `/actions/execute` remains disabled. Configuration attests the
snapshot identity; the broker now verifies stored snapshot bytes and patch context.
The Desktop runner validates local image availability and applies the profile;
the independent host boundary still needs validation. Claiming and polling recheck
approval/current context and handle revocation. External policy/identity/key
files require OS protection; path checks alone are not a security boundary.

RS2 03 outbox entries remain publication intent unless the RS2 09 publisher marks
delivery complete. PR #1 now provides live evidence of that transition, in addition
to the existing simulated-transport regression coverage.
Identity files and coordinator/database access must be protected by the local
administrator; automatic OS permission enforcement is not implemented. GitHub
sign-in is implemented and user-confirmed locally. No SQLite data import,
production deployment or dedicated-host
hostile-code execution isolation is claimed. Artifact authentication covers only
the new sealed bundles and trusted checkpoints, not legacy filesystem reports.

Before claiming controlled execution, complete RS2 06–07: dedicated Linux
isolation and dedicated-host validation of the protected synthetic database demonstration, building on
the implemented policy/approval, Ed25519 and atomic claim foundations. The legacy
HMAC gateway still has repository-local key fallback, permissive command patterns,
path-confinement limitations and a non-atomic nonce file. It is development-only;
do not give it platform credentials or expose it as a secure agent boundary.

RS2 08 now authenticates retained artifacts and checkpoints event head/count in
trusted PostgreSQL. Automatic cache reuse remains disabled. Local unsigned artifacts,
including earlier development reports, remain mutable; an internally valid audit
chain alone proves neither completeness nor authenticity. A signature authenticates
retained observations, not the semantic truth of candidate-authored tests.
Test observations can still be forged by malicious code inside execution; passing
fixture tests are not a proof against arbitrary hostile code.

Linux container controls and Python 3.12 test execution were validated on Desktop;
dedicated-host isolation, complete Python 3.12 backend compatibility and real
GitHub required-check enforcement remain unvalidated. Protected DB access denial
is now demonstrated only in Docker Desktop development. Final table equality
does not rule out transient writes or every possible bypass.
Mocked GitHub transport tests remain unit evidence only. The explicitly selected
legacy SQLite/HTTP service remains a development prototype. Cache
disablement costs performance; attempt retention/cleanup is not yet implemented.
