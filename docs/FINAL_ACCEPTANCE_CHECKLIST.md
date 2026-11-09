# Remaining release acceptance

Updated 20 October 2026. Local candidate v4-ui remains a candidate, not a final
release or a production security certification. Do not infer completion from the
existence of this checklist.

| Gate | Current evidence | Completion requirement |
|---|---|---|
| Offline installation | New venv, 37 hash-locked wheels, 213 distinct selected test cases | Repeat on a separate clean Windows Python 3.10 machine |
| Signed recovery | Two synthetic DB rounds plus actual operator-file/key/mirror offline restore on 20 October | Protected persistent/off-device backup, common-point database/asset recovery and whole-service cutover remain pending |
| Historical events | Real historical payload, new local delivery, current API head selected | Public relay delivery remains distinct; retain accurate scope |
| Live publication race | Real head change before final read passed; obsolete result, no stale success, old Check cancelled | After-final-read timing remains untested; never claim atomicity with GitHub |
| Merge enforcement | App-bound required check and observed blocked PR state | Independently verify no bypass path; do not merge the pinned demo branches |
| Restricted execution | 36 current real Docker development checks passed | Dedicated Linux host with no shared personal folders, credentials or Docker socket inside execution |
| Independent operation | Operator guide and offline candidate available | A second person follows the guide and records outcomes and problems |
| Demo and fallback | Two automated technical rounds passed: 13 checks each, 29.41s / 30.39s | Time the complete narrated demonstration twice; record actual execution with secrets excluded |

## Operator recording worksheet

Exact next steps and the candidate hash are in [OPERATOR_HANDOFF.md](OPERATOR_HANDOFF.md).
The technical rehearsal evidence is in
`evidence/rs2-12/two-modes-20261018/rehearsal.json`; it is not a narrated recording.

Record candidate archive/hash, OS, Python/Git/Docker versions, start/end times,
exact outcome and evidence location for every step. Blank entries mean pending.

1. Open the authenticated UI; show repository identity and the mode label.
2. Show exact-head PASS and authenticated evidence on PR #1.
3. Show PR #2 forbidden-path BLOCK and GitHub blocked merge state.
4. Show PR #3 required tests NOT_RUN and REVIEW_REQUIRED, never PASS.
5. Show a real authorized typed action and denial of a replayed authorization.
6. Show denied protected-database access and independently equal before/after data.
7. Explain evaluation results, development isolation limits and remaining gates.
8. Show recovery evidence and the tested candidate identity.

Keep all three PRs unmerged. Avoid opening trusted configuration, environment
variables, private-key files, browser tokens, callback URLs or database connection
strings while recording. A saved recording must be labelled as recorded evidence.
Screenshots and pytest output alone are not a completed eight-minute demonstration.

No paid host or extra GitHub write/admin permission is required merely to prepare
the local submission. Dedicated-host and independent-person gates remain pending
until the corresponding environment or person is available.
