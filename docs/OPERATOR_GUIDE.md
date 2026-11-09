# Local operator and submission guide

RepoShield has independent verification and action-control modes. Neither requires
an LLM. This guide links the tested setup paths and states the remaining acceptance
limits; it is not a fresh-machine rehearsal result.

1. Install the Python package/server dependencies using the environment recorded in
   the evaluation evidence. Start local PostgreSQL and apply migrations according
   to [LOCAL_COORDINATOR.md](LOCAL_COORDINATOR.md). Keep credentials in external
   administrator-owned files. Do not run migrations against an unrelated database.
2. Register a trusted repository/base and configure typed identities/action policy.
   Use [ACTION_POLICY.md](ACTION_POLICY.md) and [SIGNED_AUTHORIZATION.md](SIGNED_AUTHORIZATION.md).
   Put private signing keys outside both candidate code and execution environments.
3. For the current laptop demo, trusted configuration and launcher are in
   `C:/Users/pjpra/Desktop/RepoShieldTrusted`. Start the existing database with
   `docker start reposhield-live-demo-db` if stopped, then run `start-demo.ps1`
   from that external directory. The launcher refuses occupied coordinator port
   8080. Inspect existing processes before restarting; do not launch duplicate workers.
4. Visit `http://127.0.0.1:8080/ui` and sign in. The current user-confirmed login is
   local; follow [AUTHENTICATED_UI.md](AUTHENTICATED_UI.md) for role/config details.
   Repository and run views display real persisted results.
5. For GitHub, follow [GITHUB_APP.md](GITHUB_APP.md) and
   [LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md). The temporary tunnel must target only
   the webhook relay on loopback port 8910, never the whole coordinator. Its URL
   expires/changes; verify public UI/API routes return 404 before updating the App
   hook. Redeliver failed real events after recovery. Never substitute manual results.
6. Keep demo PRs unmerged while their reviewed base is pinned. A base change requires
   trusted review and explicit activation; candidate policy cannot activate itself.
7. For controlled execution, follow [RESTRICTED_EXECUTION.md](RESTRICTED_EXECUTION.md)
   and [PROTECTED_DATABASE_DEMO.md](PROTECTED_DATABASE_DEMO.md). Docker Desktop
   demonstrations are development evidence. Do not claim a hostile-code boundary
   until dedicated Linux acceptance succeeds. The live UI setup does not enable
   an agent executor or dynamic verification tests.
8. Reproduce measurements using [EVALUATION_REPORT.md](EVALUATION_REPORT.md).
   Retain output directories, package versions and raw samples. Keep external
   credentials out of any submission archive; synthetic fixture keys/text are not
   real credentials. No automatic cache reuse is enabled.

When stopping the demo, stop its specific coordinator/workers, webhook relay and
tunnel; Windows Python launchers may have children, so verify process lineage.
Stop only `reposhield-live-demo-db` if desired. Preserve its volume and trusted
files; do not stop unrelated Docker containers. Rehearse backup/restore and clean
restart before claiming release readiness (RS2 12).

Suggested demonstration sequence: PR #1's authenticated PASS; PR #2's forbidden
path BLOCK and blocked merge state; PR #3's mandatory-test NOT_RUN and non-success;
signed evidence replay; then the separately configured allowed action, replay
denial and protected synthetic database demonstration. Label any saved recording
as recorded evidence, not current live execution. Do not demonstrate privileged
actions against personal or production data.
