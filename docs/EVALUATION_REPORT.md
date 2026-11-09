# RepoShield evaluation — 16 October 2026

This is a local synthetic evaluation, not production security certification.
Both product modes run without an LLM. The evaluation preserves Python and uses
the existing demo plus explicitly authored fixtures. No paid service was provisioned.

## Measured results

| Experiment | Observed result | Scope |
|---|---|---|
| Change verification | 20/20 expected verdicts matched | Ten original demo branches plus ten additional fixtures |
| Typed action policy | 15/15 expected decisions matched | Read, patch, tests, review, unsupported operations and invalid context/paths |
| Seeded regression detection | Full 12/12; safe-selected 12/12 | Both suites actually executed for each mutation |
| Selected test files | 34 versus 108 across twelve runs | 68.5% fewer file selections; not a test-case count |
| Test execution time | Selected 17.371 s versus full 19.011 s | 8.6% lower total measured process time in this run |
| Incremental graph equivalence | 3/3 matched full rebuild edge sets | 200 synthetic Python files, five edits, seeds 7/11/19 |
| Durable scheduler | 20 enqueue/first-claim cycles | Real PostgreSQL in disposable schemas |
| Signed action authorization | 20 issue/claim cycles; 20/20 replays rejected with 409 | Real Ed25519 and PostgreSQL; no action execution |

Median service-call timings over 20 samples: enqueue **57.962 ms**, initial task
claim **7.928 ms**, persisted action authorization **14.149 ms**, token issuance
**15.544 ms**, atomic claim **15.293 ms**. These include local service/database
work and exclude HTTP, queue wait, worker execution and fixture setup. They are
not production throughput estimates. Raw samples, rather than only medians, are retained.

The policy-only experiment separately records 100 timing samples per case; it
must not be substituted for end-to-end signed authorization timing. An ALLOW in
that experiment does not mean an action executed. The claim experiment explicitly
asserts `unknown-outcome` with execution disabled, then tests replay rejection.

## Reproduction and raw inputs

Use the existing `.venv-rs2` environment from the workspace root. Set
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. Each output directory must be new; runners
refuse to replace existing evidence.

```powershell
.venv-rs2/Scripts/python benchmark/evaluate_v2.py --output docs/evidence/rs2-11/new-run
.venv-rs2/Scripts/python benchmark/selection_v2.py --output docs/evidence/rs2-11/new-selection
```

For database timings, set `REPOSHIELD_TEST_DATABASE_URL` to an operator-managed
local PostgreSQL connection outside shell history/source, and set
`REPOSHIELD_EVAL_OUTPUT` to a new evidence directory. Then run:

```powershell
.venv-rs2/Scripts/python -m pytest benchmark/test_overhead.py -q -ra --basetemp=.test-new-overhead
```

The fixtures create randomly named schemas and remove only those schemas after
each test. They create ephemeral signing keys outside candidate/source directories.
Tokens, private keys and database URLs are not written to benchmark results.
Prefer a dedicated evaluation database when reproducing independently.

Recorded data:

- [Final change/policy run](evidence/rs2-11/run-02/summary.json), with individual
  raw result JSON, exact patches and patch digests, original synthetic Git objects,
  full environment package versions and harness digest in the same directory.
- [Full/selected mutation executions](evidence/rs2-11/selection-01/results.json),
  including mutation strings, paths, actual stdout/stderr, exit codes, durations,
  testcase failures and retained JUnit XML in each fresh execution copy.
- [Scheduler samples](evidence/rs2-11/overhead-01/scheduler.json) and
  [authorization samples](evidence/rs2-11/overhead-01/authorization.json).
- The first change run remains under `run-01`; it matched 20/20 and 15/15 but
  emitted a Pydantic serialization warning from an unvalidated benchmark override.
  The harness now validates the complete request before timing policy evaluation.
- Initial overhead collection failed with two setup errors because `demo_repo`
  was not imported into the opt-in benchmark module. After fixing that import,
  **2 passed, 1 warning in 7.32 s**. The remaining warning is the existing Starlette
  deprecated AnyIO alias. Existing regression assertions were not changed.

## Algorithms and architecture

Verification resolves immutable base/head commits and loads trusted base policy.
Python AST dependencies form a file graph. The incremental head graph reparses
changed nodes and updates dependencies; graph comparison checks equality against
a fresh rebuild. Reverse reachability selects impacted tests, with conservative
fallbacks and explicit policy-required files. Test evidence and deterministic
findings produce PASS, BLOCK or REVIEW_REQUIRED. Missing required evidence cannot
become PASS. See [the master architecture](REPOSHIELD_MASTER_PLAN.md),
[threat boundaries](THREAT_MODEL.md) and [authenticated evidence](AUTHENTICATED_EVIDENCE.md).

Controlled actions intersect administrator, repository and session scopes before
authorization. Approval is separate from the raw decision. Ed25519 binds exact
context, limits, resource and expiry; a PostgreSQL transaction consumes the claim
once. The separate broker applies execution restrictions. Policies alone do not
provide isolation. See [action policy](ACTION_POLICY.md),
[signed authorization](SIGNED_AUTHORIZATION.md) and [execution](RESTRICTED_EXECUTION.md).

## Limitations and disclosed gaps

The full/selected experiment runs only trusted, authored synthetic fixtures using
the development subprocess backend. It is not safe for arbitrary candidate code
and does not close dedicated Linux-host acceptance. Each suite gets a fresh copy;
full runs precede selected runs, so caching/order effects may favor the latter.
There is one timing observation per mutation, no confidence interval, and no claim
that this small corpus generalizes. Graph timings include only three seeded small
graphs. The original algorithm may conservatively select more tests on other inputs.

No misses were observed in this fixed twelve-mutation corpus. No statistical flake
study was performed. The fixtures are synthetic, not independently sampled bugs.
Additional change cases include related forbidden-path variants and are not twenty
independent vulnerability classes. Existing Desktop broker/protected-database tests
provide separate development evidence; the fifteen policy cases do not replace them.

Live GitHub PASS, BLOCK, missing-test REVIEW_REQUIRED and old-event deduplication
have been observed separately. Unprocessed delayed events, publication races,
controlled infrastructure failure, installation revocation/recovery and full merge
rejection acceptance remain pending. Dedicated VM, independent multi-user review,
deployed HTTPS UI and fresh-machine rehearsal also remain pending. The verification
worker is still static-only: dynamic test-dependent live PRs cannot receive PASS.

No backend code changed during this evaluation. The historical full-suite result
remains 405 passed/1 skipped/1 warning; it is not presented as a new full-suite run.
RS2 11's local measurement/report work can proceed under the user's instruction
to continue, but submission readiness depends on those unresolved acceptance gaps.
