# RepoShield submission candidate

Prepared 2 November 2026. This is a locally validated submission candidate;
dedicated Linux execution and independent-machine acceptance remain pending.

## What the project demonstrates

RepoShield independently verifies proposed code changes with deterministic policy,
dependency analysis and test evidence. Its separate action-control mode authorizes
typed requests, binds signed decisions to exact inputs, consumes authorization once,
and executes supported actions through a restricted broker. Neither mode requires
an LLM. Missing mandatory evidence cannot become PASS.

The live GitHub verification worker is static-only. Its README-only PASS is valid
when no tests are required; required but unexecuted tests remain REVIEW_REQUIRED.
Real dynamic action execution has been demonstrated on Docker Desktop and is
labelled DEVELOPMENT EXECUTION. Do not describe it as dedicated-host acceptance.

## Reviewer reading order

1. `docs/IMPLEMENTATION_STATUS.md`: actual work, results and limitations.
2. `docs/REPOSHIELD_MASTER_PLAN.md`: scope and trust boundaries.
3. `docs/EVALUATION_REPORT.md`: measured evaluation and methodology.
4. `docs/OPERATOR_GUIDE.md`: run the configured demonstration.
5. `docs/OPERATOR_HANDOFF.md`: independent installation and remaining steps.
6. `docs/FINAL_ACCEPTANCE_CHECKLIST.md`: unfinished release gates.

## Validation included

The full source regression run on 1 November finished with **406 passed, one
skipped, zero failures/errors**, in 292.72 seconds. PostgreSQL and Docker development
checks were enabled. `test_symlinked_report_is_rejected` skipped because this
Windows environment did not permit symlink creation. See
`docs/evidence/final-20261101/tests.xml`; a skip is not acceptance evidence.

Earlier evidence includes offline installation of 37 hash-locked wheels, 213
distinct selected installed-wheel cases, two signed database recovery rounds,
two fresh technical rehearsals, real GitHub failure/revocation/stale-publication
checks, and an offline restore rehearsal of actual operator keys/configuration and
the public mirror. Dates and scopes remain attached to their original reports.
The source regression does not replace independent installed-wheel validation.

## Installation

The wheelhouse targets Windows x64 with Python 3.10 already installed. Git is also
required for verification tests. From the extracted archive directory:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install --no-index --require-hashes --find-links wheels -r requirements-release-windows-py310.lock
.venv/Scripts/python -m pip check
```

Follow OPERATOR_HANDOFF.md to run the independent verification subset. UI/broker
operation additionally needs administrator-owned external configuration and the
documented PostgreSQL/Docker setup. Credentials are deliberately not distributed.
The Windows wheelhouse is not a Linux dependency bundle.

## Archive identity

`MANIFEST.json` binds every packaged file by length and SHA-256.
`CANDIDATE_PROVENANCE.json` identifies the original candidate and evidence archives.
The consolidated archive retains the tested 0.2.1 application wheel; its filename
and companion SHA-256 receipt distinguish this candidate from earlier archives.
It is not a new production release tag. No keys, live database dumps, runtime
configuration or temporary working repositories are included.

## Still required

- A dedicated Linux VM/host without shared personal folders or platform credentials,
  followed by isolation and failure-recovery acceptance on that host.
- Another person/machine completing the independent installation and operation.
- Two narrated demonstration runs and a fallback recording of actual execution.
- An operator-selected encrypted permanent backup and whole-service recovery check.
- Independent inspection of branch protection and bypass settings; no unperformed
  merge attempt is claimed as a rejected merge.

A VM is a separate virtual computer running Linux on the laptop. We must inspect
available virtualization support before choosing its setup. No VM has been
provisioned, no paid service is required by this guide, and no purchase is authorized.
