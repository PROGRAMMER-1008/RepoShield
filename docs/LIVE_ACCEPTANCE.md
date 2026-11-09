# Live demo acceptance remaining after PR #1

17 October: controlled mirror unavailability produced a real infrastructure-failure
Check on PR #3. Real installation suspension/access denial, blocked worker claim,
blocked publication and explicit recovery passed in an isolated schema. No merge
was attempted. See IMPLEMENTATION_STATUS.md for receipts and scope. The remaining
ordering tests must exercise first-arrival stale events or in-flight publication,
not count the earlier duplicate-event replay again.

Recorded 16 October 2026. Repository: `Repoguard-demo-org/Repoguard-demo`.
The existing App has Contents/Pull requests read and Checks write. Creating commits,
PRs and branch-protection rules requires the operator's GitHub account. Do not
expand the execution agent's permissions or copy credentials into the repository.

## Protect main

Completed by the operator on 16 October. The branch API independently confirms
protection enabled, App ID 5339672, the required check context, and enforcement
level `everyone`. Full rule details require administration access and returned
403 for this App. Remaining settings below are operator-reported. PR #1 remains
open and its successful head is reported `clean`; no PR has been merged.

Open https://github.com/Repoguard-demo-org/Repoguard-demo/settings/branches and add
a classic branch-protection rule with pattern `main`:

- Require a pull request before merging; required reviewer approvals may remain off
  for this one-person synthetic demo.
- Require status checks to pass, selecting `RepoShield / verification` and its
  expected App source `repoguard-demo` (App ID 5339672).
- Require branches to be up to date before merging.
- Do not allow bypassing the above settings; no actor bypass list.
- Leave force pushes, deletions and merge queue disabled.

Save. Configuration alone does not prove enforcement. Keep every demo PR unmerged:
the current trusted base is `07f22c74f0b9e42c715adef1573b767339e99e02` and a changed
base requires explicit trusted review/activation.

## Minimal negative fixtures

The forbidden-path fixture is completed as PR #2: authenticated BLOCK, failed
current-head Check, and GitHub merge state `blocked`. No merge attempt was made.
The mandatory-test fixture is completed as PR #3: authenticated REVIEW_REQUIRED,
two required auth test files selected but NOT_RUN, failed Check and merge state
`blocked`. No merge attempt or bypass verification has been performed.

Create each branch from `main`, not from another test branch. No runnable workflow
or real credential is needed for these tests.

| Branch | Exact change | Expected result |
|---|---|---|
| `reposhield-demo-block` | Add `.github/workflows/reposhield-denied.txt` containing `Synthetic forbidden-path acceptance fixture.` | BLOCK because the reviewed policy forbids changes under `.github/workflows/**`; GitHub Check failure |
| `reposhield-demo-required-tests` | Append `# Synthetic mandatory-test evidence acceptance fixture.` to `auth/login.py` | Non-success because the auth path requires tests and this static worker cannot supply their execution evidence; never PASS |

Open each PR into `main` and send its `/pull/<number>` URL. Inspect the exact current
head's Check and signed evidence, then record whether GitHub prevents merging due
to the required RepoShield check. A failed Check alone is not merge-enforcement
evidence. Do not merge even if a configuration mistake leaves the merge button enabled.

The operator added a new README-only commit on PR #1. Its new Check passed and
evidence authenticated; redelivery of the already-processed original event returned
202 without changing either revision's stored Check or delivery records. Exact
SHAs and IDs are in `evidence/rs2-live-20261016/pr-1-revision-redelivery.json`.
This validates old-event deduplication after a newer revision, not a previously
unprocessed delayed event or an in-flight stale publication race.
A controlled infrastructure fault and installation suspension/recovery were
validated on 17 October; see `evidence/rs2-live-20261017/`. The failure Check was
real, and suspension denied fresh access before the installation was restored.

On 18 October, `benchmark/live_stale_event_check.py` retrieved the historical
GitHub delivery payload and operator-re-signed it into a fresh local schema.
This previously unseen local delivery resolved to the real current API head,
not the historical payload head. A separate queued historical-head publication
became obsolete before creating a remote Check. The temporary mirror/schema were
removed. Evidence: `evidence/rs2-live-20261018/stale-first-arrival-retry/result.json`.
This is a first-local-arrival rehearsal using real API/Git data, not proof of a new
GitHub-origin webhook delivery through the public relay.

The operator subsequently changed PR #1 while a real publication was paused before
its final API read. The genuine old-head PASS became obsolete, with no remote
success conclusion; the rehearsal Check was cancelled. New head `0f9f6a8` received
its own authenticated static PASS (Check 117739405466) through explicitly labelled
operator intake, and GitHub returned merge state `clean`. See
`evidence/rs2-live-20261018/publication-race/`. This validates the race before the
final read, not atomicity with GitHub or a race after that read. PR #1 remains unmerged.

## Evidence and limitations

`evidence/rs2-live-20261016/pr-1.json` records the completed positive static case and
duplicate delivery. The initial webhook failed with 502; a replacement temporary
tunnel and real event redelivery restored processing. All services depend on the
laptop staying online. No dynamic-test or dedicated Linux-host acceptance is implied.

Official rule guidance:
https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule
