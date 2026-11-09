# Release candidate preparation (RS2 12)

This is a local candidate package and recovery rehearsal, not release acceptance.
Dedicated Linux isolation, complete live GitHub adverse-case testing, independent
reviewer operation, public HTTPS UI and a fresh-machine run remain open gates.

## Package

### UI candidate, 17 October

The separate `ui-candidate-20261017` build includes the redesigned product UI.
Its wheel was built from a clean source copy excluding `__pycache__`, `*.pyc` and
`*.pyo`, without dependency downloads. All 91 Python source files were compared
byte-for-byte against the resulting wheel. The earlier v3 archive, wheel and lock
remain unchanged. Both candidates retain development version 0.2.1; identify the
candidate by its archive and SHA-256 receipt, not the version string alone.

The new wheel SHA-256 is
`165c7d2e60b0c6ae3a5473783927e21d84f02aaaa94bbf7c1720d01a85a1154a`.
Its candidate-specific lock binds this wheel and the same 36 dependency wheels.
Install an extracted candidate using the offline commands below. Tests must run
from the extracted directory with the installed package location checked; importing
workspace source invalidates an installed-wheel check. No backend test assertions
were edited for this candidate.

Two signed recovery rounds also passed against this installed UI candidate, with
all six real verification outcomes authenticated after restore/restart and wrong
keys rejected. Temporary keys and the disposable container were removed. Evidence
is recorded in `docs/evidence/rs2-12/ui-candidate/`; the candidate's canonical
`wheel.json`, `clean-install.json` and signed recovery report refer to its own run.
Earlier candidate archives retain their original reports. This remains same-host
validation, not fresh-machine or dedicated Linux acceptance.

The wheel is built with the existing build environment, without dependency
downloads or build isolation. Its Python members are compared byte-for-byte with
source; migrations and demo policy presence are checked. The candidate uses the
existing version 0.2.1, not a new final-release tag.

`requirements-release-windows-py310.txt` pins the installed runtime/evaluation
dependencies for this tested Windows Python 3.10 environment. It is not a
cross-platform lock. On 17 October, a separate
`requirements-release-windows-py310.lock` was generated from 37 acquired wheels
(including RepoShield) and used for a `--no-index --require-hashes` installation in
a new venv. The offline candidate includes these exact Windows CPython 3.10 wheels;
its packager verifies their set and hashes against the tested manifest. This does
not supply Python itself, Git, Docker, PostgreSQL images or a fresh operating system.

```powershell
.venv-rs2-build/Scripts/python -m pip wheel . --no-deps --no-build-isolation --wheel-dir .rs2-release/wheels
.venv-rs2/Scripts/python -m pip install --no-deps --no-index --target .rs2-release/installed .rs2-release/wheels/reposhield-0.2.1-py3-none-any.whl
```

The installed target uses the existing environment's dependencies. Rehearsal checks
the imported package location so workspace source cannot silently substitute for
the wheel. This is not described as a fresh-machine install.

For an extracted offline candidate on Windows x64 with Python 3.10 already installed:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install --no-index --require-hashes --find-links wheels -r requirements-release-windows-py310.lock
.venv/Scripts/python -m pip check
```

Use a fresh output location and preserve the candidate archive/manifest for
comparison. Hashes bind the acquired artifacts; they are not a supply-chain audit
of dependency authors. This lock is intentionally platform-specific.

## Disposable database recovery

`benchmark/rehearse_release.py` creates a uniquely named local PostgreSQL container
from the cached pinned digest, with 512 MiB/one CPU, a loopback port and an
ephemeral password. The port defaults to 55434 and is configurable; Docker refuses
an occupied binding. It never reads the live demo config. Each of two rounds creates
new source/restored databases, migrates, runs real static PASS/BLOCK/REVIEW_REQUIRED
jobs, dumps with `pg_dump -Fc`, restores with `pg_restore`, and compares row counts
and canonical row-text hashes for every public table. It restarts the disposable
container and compares again. Only its own container/anonymous volume are removed.

```powershell
$env:PYTHONPATH = (Resolve-Path .rs2-release/installed).Path
.venv-rs2/Scripts/python benchmark/rehearse_release.py --installed-root .rs2-release/installed --output docs/evidence/rs2-12/new-rehearsal
```

Output must be a new directory. Dumps contain only generated synthetic records.
The script does not restore real GitHub tokens, signing keys, trusted policy files,
bare mirrors or snapshots. Those external assets need a separately protected backup
and recovery procedure before operational disaster-recovery claims are justified.
Database row equality alone is not signed-evidence replay or full product recovery.

The optional `--signed-evidence` mode adds synthetic external Ed25519 keys and a
content-addressed snapshot. It seals all three real worker outcomes before dumping,
copies the temporary key/snapshot assets to a separate recovery directory, restores
the database and authenticates each checkpoint using a public-key-only replay
configuration. It checks that a restored private key can sign a challenge, verifies
snapshot bytes, rejects a deliberately wrong public key, then repeats evidence
authentication after restart. No temporary key bytes enter the evidence directory
or candidate archive; temporary external assets are cleaned up.

On 17 October, **two signed recovery rounds passed** in
`evidence/rs2-12/rehearsal-signed-recovery/rehearsal.json`: six original real
PASS/BLOCK/REVIEW_REQUIRED checkpoints authenticated after restore and restart;
wrong keys were rejected in both rounds. Public-table hashes remained unchanged.
This closes synthetic signed-evidence/key/snapshot recovery, not recovery of live
OAuth/App credentials, protected policy files, bare mirrors or a separate host.

Actual result: `evidence/rs2-12/rehearsal-03/rehearsal.json` records **two passing
rounds**, each with real PASS/BLOCK/REVIEW_REQUIRED, all-public-table equality after
restore and equality after container restart. The container/anonymous volume were
removed. The first two attempts could not reach Docker's randomly published port;
the successful run uses explicit loopback 55434. Both failed attempts cleaned up
their containers. No firewall settings or live database configuration were changed.
`pip check` also passed. This uses existing dependencies, not a clean OS installation.

## Actual operator assets, 20 October

`benchmark/rehearse_operator_assets.py` additionally validated offline same-host
restoration of the actual trusted keys/configuration/identity files and public bare
mirror. It used an owner-only temporary directory outside source/execution, verified
key challenges and mirror refs/integrity, preserved the originals and removed the
temporary secret copies. Only a sanitized result is retained at
`evidence/rs2-12/operator-assets-20261020/result.json`.
This does not create a permanent backup or establish live service cutover,
cross-machine recovery or a common database/asset recovery point.

## Submission sequence (eight-minute target, not yet timed)

| Time | Demonstration |
|---|---|
| 0:00–1:00 | Explain the independent verification and action-control modes and trust boundaries |
| 1:00–2:00 | PR #1 exact-head PASS and authenticated evidence |
| 2:00–3:00 | PR #2 forbidden path BLOCK and GitHub blocked state |
| 3:00–4:00 | PR #3 required tests NOT_RUN, REVIEW_REQUIRED, non-success Check |
| 4:00–5:00 | Allowed typed action, signed claim and replay denial using the configured development demonstration |
| 5:00–6:00 | Protected synthetic database direct-access denial and independently verified unchanged state |
| 6:00–7:00 | Evaluation: real mutation detection, selection timing and limitations |
| 7:00–8:00 | Recovery evidence and explicit remaining deployment/acceptance gaps |

No fallback video has been recorded. A future recording must show actual results,
be labelled recorded, omit credentials, and not masquerade as current execution.
Keep live demo PRs unmerged while the trusted base remains pinned.

On 18 October, `benchmark/rehearse_two_modes.py` completed two fresh automated
technical rounds in 29.41s and 30.39s, each with 13 passing cases and no skips.
These cover all ten verification scenarios, missing mandatory evidence, signed
one-shot claim/replay, and real restricted patch/test execution with denied direct
protected-database access and external equality checks. Raw XML and synthetic
database observations are under `evidence/rs2-12/two-modes-20261018/`.
This advances technical repeatability; the eight-minute narrated presentation
and fallback recording remain pending. See OPERATOR_HANDOFF.md for operator steps.

## Candidate contents and exclusions

Use an explicit file list for a candidate archive: wheel, dependency pins,
operator/release/evaluation documents and reproduction scripts. Exclude trusted
configuration, private keys, tokens, runtime database dumps, candidate worktrees,
virtual environments and all unrelated personal files. Synthetic recovery dumps
remain local evidence, not part of the distributable package. Verify an archive
manifest and SHA-256 hashes after creation. A filename/content-pattern scan reduces
accidental inclusion risk but is not a proof that arbitrary files contain no secrets.
