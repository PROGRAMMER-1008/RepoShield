# Operator steps to close remaining acceptance

18 October 2026. No purchase is required for these steps. Keep the demo PRs unmerged.

## 1. Independent Windows installation

Give a second person this candidate archive, without the trusted runtime folder:

`reposhield-offline-windows-py310-20261017-v4-ui.zip`

Expected SHA-256:
`7d92de2578a0ff074f2ec0e6c5b3571f1a140b62360dec81339daeddb9454bc5`

Use a separate Windows x64 machine with Python 3.10 and Git installed. Extract the
archive into a new folder. From that extracted folder run:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install --no-index --require-hashes --find-links wheels -r requirements-release-windows-py310.lock
.venv/Scripts/python -m pip check
.venv/Scripts/python -c "import reposhield; print(reposhield.__file__)"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
.venv/Scripts/python -m pytest tests/test_e2e.py tests/test_policy_selector.py tests/test_analyzer_graph.py tests/test_portability.py -q -ra --junitxml=independent-tests.xml
```

The import must point inside the new `.venv`, not an existing source checkout.
Expected scope: 39 verification/graph/selection/portability cases. This does not
validate the PostgreSQL UI or Docker broker. Send the test summary, machine/OS and
Python/Git versions, archive hash, and any failed steps. Do not send credentials.

For independent operation, the person must also follow OPERATOR_GUIDE.md on an
appropriately configured demo environment and record problems without relying on
the original developer to silently fix them. Installation alone does not close
independent full-demo acceptance.

## 2. Dedicated Linux execution validation

Provide a disposable Linux VM or separate host. Keep host shared folders,
clipboard/file integration, personal data and platform credentials out of it.
Give only the trusted executor the Docker administrative route; never expose the
Docker socket or platform private signing key to agent execution. Use only synthetic
repositories and the protected synthetic database fixture.

Follow RESTRICTED_EXECUTION.md and PROTECTED_DATABASE_DEMO.md. Repeat the isolation,
resource-limit, credential exclusion, replay, direct network bypass and external
database comparison checks there. Validate watchdog/reboot handling separately.
Record topology and exact image identities. The Windows wheelhouse is not a Linux
dependency bundle. Do not copy the Windows runtime or assume Docker Desktop
results establish this acceptance gate.

Once a host exists, provide its connection method and resource limits, not private
keys or passwords in chat. No cloud VM should be purchased just to satisfy this
document without separate cost approval.

## 3. Narrated demonstration and fallback recording

Follow the eight-minute sequence in RELEASE_REHEARSAL.md. Record the actual UI,
GitHub Checks and real action execution. Keep the terminal away from trusted
configuration, environment dumps, login callback URLs and secret files. Repeat
the complete presentation twice and record its duration and failures. Label the
fallback file with recording date and candidate identity. Automated technical
rehearsals are supporting evidence, not a substitute for the narrated recording.

## 4. Protected operator assets and branch enforcement

Keep live App/OAuth credentials, policy/configuration, private signing keys and
bare mirror backups outside the submission folder and execution environment.
Use an access-controlled encrypted backup destination selected by the operator.
Restore into a separate trusted location; validate key/public-key correspondence,
configuration references and mirror integrity before attempting isolated recovery.
Never overwrite working credentials merely to demonstrate restore. Existing
synthetic recovery evidence does not establish recovery of these live assets.
On 20 October, an additional offline rehearsal restored the actual 11 operator
files and public mirror, verified both signing keys and operator identity, checked
App/UI schemas and mirror integrity, and removed temporary copies. See
`evidence/rs2-12/operator-assets-20261020/result.json`. No permanent backup or live
cutover was performed. Select an encrypted backup destination outside the submission
tree before treating disaster recovery as complete; coordinate database and asset
versions and validate the restored service on a separate trusted environment.

Have the repository owner independently inspect main's required App-bound check,
up-to-date requirement and no-bypass setting. Record what GitHub actually shows.
Do not merge or weaken protection to obtain evidence. Current blocked states and
the passing live stale-publication race are already recorded; an unperformed merge
request must not be described as an actual rejected merge.
