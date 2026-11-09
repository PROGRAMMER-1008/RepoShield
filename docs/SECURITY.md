# Security model & honest limits

The current scope and authority boundaries are defined in [THREAT_MODEL.md](THREAT_MODEL.md).
This prototype is not yet a controlled-session execution service; see
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for validated milestones.

## What RepoShield defends against
An AI agent (or a compromised contributor) producing a change that silently crosses an architectural boundary, edits CI or
credentials, weakens tests, adds dependencies, skips relevant tests, or tries to rewrite the rules that judge it.

## Design rules that carry the security weight
| Rule | Where |
|---|---|
| The deterministic core decides. No LLM can turn FAIL into PASS (there is no LLM in the core). | `verdict.py` |
| Missing evidence is never safety: `UNKNOWN` → `REVIEW_REQUIRED`. | `models.py`, `verdict.py` |
| Policy is read from the **base** branch, not from the change under test. Editing `.reposhield.yml` also forces review. | `engine.py`, `checks.py` |
| Selective testing is conservative: unmapped file / config change / no reaching test ⇒ full suite. | `selector.py` |
| Legacy development actions use HMAC and expiring tokens; nonce-file checks do not prevent simultaneous replay. | `actions.py` |
| Audit chains detect internal edits/reordering; truncation or replacement needs a separate trusted checkpoint (RS2 08). | `audit.py` |
| Secrets matched in diffs are redacted in all output. | `checks.py` |
| The test report written inside the sandbox is treated as hostile: no symlinks, size-capped, strict schema, exit status cross-checked. | `engine.load_test_report` |
| Unsigned verdict, graph, parse and coverage caches are not trusted by verification; each attempt recomputes evidence. | `engine.verify` |
| Files too large to analyse (>2 MB) are UNKNOWN, never silently ignored. Parser crashes (deep nesting, bad bytes) are contained. | `analyzer.py`, `checks.py` |
| Verification attempts have separate output directories; equivalent requests cannot overwrite each other's artifacts. | `engine.verify` |
| `reposhield doctor` demonstrates, on the machine at hand, which isolation properties actually hold. | `doctor.py` |

## Limits you must know about
1. **Subprocess sandbox is a dev backend, not a security boundary.** It applies rlimits, a scrubbed environment, process-group
   kill and (if the host permits `unshare`) network isolation. Untrusted execution requires the dedicated Linux boundary planned in RS2 06, not merely selecting a backend.
2. **Docker is not a perfect boundary either** — containers share the host kernel. The docker backend adds no network,
   read-only rootfs, dropped capabilities, `no-new-privileges`, pid/memory/cpu limits, non-root user, Docker's default seccomp
   profile. For hostile multi-tenant use, add gVisor/Firecracker. *The docker backend's command line is unit-tested; it has not
   been run end-to-end in the environment this prototype was built in.*
3. **Test results come from inside the sandbox.** Malicious test code can forge the result file or exit status. RepoShield
   cross-checks the two and treats mismatches as UNKNOWN, but that is not proof. Real isolation of the reporter is future work.
4. **Coverage baselines** are read (as SQLite) from the sandbox workspace by the host process — another reason to prefer a
   hardened runner and to treat `.reposhield/out` as untrusted input.
5. **Static analysis is file-level and Python-only.** Dynamic imports with non-constant targets are reported as UNKNOWN for
   guarded packages, but reflection, plugins, `exec`, and string-built module names can hide dependencies. "Impact" means
   *potentially affected*, never *proven broken*.
6. **Test selection works at test-file granularity.** Verification currently falls back from `balanced` to `safe` because
   local coverage persistence is unauthenticated. Baseline collection remains available for development experiments.
7. **The gateway signing key** lives in `.git/reposhield/signing.key` (or `REPOSHIELD_SIGNING_KEY`). Whoever holds it can mint
   tokens. This legacy development facility must not be exposed to agents. RS2 05 must move private keys outside repository
   and executor, adopt Ed25519 and atomically claim authorization. Do not provision platform credentials into execution.
8. **Not claimed:** formal correctness, completeness of bug detection, or protection against a malicious maintainer.

## Service mode (`reposhield serve`)
| Rule | Where |
|---|---|
| Webhook disabled unless `GITHUB_WEBHOOK_SECRET` is set; HMAC-SHA256 checked in constant time; replayed delivery ids ignored. | `server/github.py`, `server/app.py` |
| Webhook repos must be on an explicit allow-list (`--allow-repo`). Malformed shas / base refs never reach git. | `server/github.py` |
| Webhook execution requires the Docker backend and an immutable image digest, unless an explicit development override is set. These configuration checks do not establish RS2 06 isolation. Missing mandatory execution evidence is non-successful. | `engine.py` (`untrusted_code`) |
| Local-path verification is off unless `--allow-local ROOT`; paths are resolved (symlinks) and confined to those roots; refs are validated (no `-option` injection, no `..`). | `server/app.py`, `gitutil.resolve` |
| Non-loopback bind refused without `REPOSHIELD_API_TOKEN`; Bearer or Basic auth on API and dashboard. | `cli.py`, `server/app.py` |
| Dashboard escapes every dynamic value, sets a strict CSP, embeds reports in a sandboxed iframe, and protects its form with a CSRF token. | `server/dashboard.py` |
| PR comments neutralise `@mentions` coming from repo-controlled strings. | `server/worker.py` |
| A run that errors is reported to GitHub as `error`, never green; interrupted runs are re-queued after a restart. | `server/worker.py`, `server/db.py` |

**Known limits of the service:** the GitHub token is passed to `git fetch` on the command line (visible to local `ps`; use a
credential helper or a GitHub App installation token in production); SQLite + in-process threads suit one host, not a cluster
(Postgres + a real queue are the next step); commit statuses are used instead of Check Runs (those require a GitHub App);
the dashboard has a single shared API token, no per-user accounts; the HTTP layer is not rate-limited.
