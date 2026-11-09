# RS2 10 validation, 15 October 2026

Results: baseline **372 passed, 1 skipped, 1 warning / 269.12 s**; focused UI
**33 passed, 1 warning / 15.98 s**; final full suite **405 passed, 1 skipped,
1 warning / 295.51 s**. All commands finished successfully after local network
access was authorized. The disposable database and preview server were stopped.

Before source changes: backup `.rs2-10-original.zip`; no root Git repository.
Baseline and final suite use a disposable PostgreSQL 17 container bound only to
127.0.0.1:55432, a separate random schema per test, and the previously cached
restricted Docker image. No paid service or remote GitHub call was used.

Test environment variables:

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`
- `REPOSHIELD_TEST_DATABASE_URL`: disposable local PostgreSQL connection
- `REPOSHIELD_TEST_RUNNER_IMAGE=reposhield-restricted@sha256:d7fa14e9b41f25dbd10b7872c5dc8d85e3741c7e6a00d5b6b05a7e8f7502a66e`
- `REPOSHIELD_TEST_PROTECTED_DATABASE=1`
- `REPOSHIELD_TEST_EVIDENCE_DIR=docs/evidence/rs2-10`

Commands run with `.venv-rs2/Scripts/python`:

```text
-u -m pytest -q -ra --tb=short --basetemp=.test-rs210-baseline
-u -m pytest tests/test_product_ui.py -q -ra --tb=short --basetemp=.test-rs210-ui-final
-u -m pytest -q -ra --tb=short --basetemp=.test-rs210-full
-m pip check
-m compileall -q reposhield tests/test_product_ui.py
```

The first unprivileged UI test invocation hit a Windows localhost permission
failure. The approved rerun passed with real PostgreSQL, without test changes to
work around that error. The first focused implementation passed 29 cases; four
additional malformed-request, bounded-state, empty-configuration and mandatory
evidence regressions brought the focused suite to 33 passing cases.

Package build uses `.venv-rs2-build/Scripts/python -m build --wheel --no-isolation
--outdir .rs2-03-dist`. Build passes with pre-existing demo-data discovery warnings.
`pip check` reports no broken requirements; compilation succeeds. `wheel-check.json`
records the wheel hash and byte-for-byte checks of all updated runtime modules.
`source-changes.json` compares Python files with the pre-edit backup: existing test
and runner sources unchanged, no Python source deleted.

Focused tests optionally write sanitized HTML using
`REPOSHIELD_TEST_UI_PREVIEW_DIR=docs/evidence/rs2-10/preview`. The repository/action
pages were visually inspected and the verification page's accessible contents
checked in the in-app browser via a temporary loopback-only static server. CSRF
values are removed. Links/forms require the real application and do not work in
these snapshots. One action rendering fixture inserts a known unknown-outcome
record; it is not an executed-action result. Real worker verification and existing
Docker action tests are separate evidence. Browser live OAuth was not tested.

See `baseline.txt`, `ui-tests.txt`, `full-suite.txt`, `package-build.txt`, and
`environment.txt` for actual outputs. The Windows symlink test skip and Starlette
AnyIO deprecation warning are existing limitations. No dedicated Linux VM or live
GitHub/OAuth acceptance is claimed.
