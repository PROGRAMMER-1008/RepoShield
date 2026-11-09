# Protected database demonstration (RS2 07 development)

This is a real local Docker Desktop demonstration using synthetic data. Dedicated
Linux VM acceptance for RS2 06–07 remains pending. It does not establish a secure
host boundary against arbitrary hostile code on a personal laptop.

## What runs

`tests/test_protected_database.py` creates a disposable PostgreSQL 17 container,
separate from the coordinator database, with randomly generated credentials.
Only its PostgreSQL port is published, on host loopback at a dynamically assigned
port. The fixture creates products, customers and orders, two synthetic rows each.
The only email addresses use `example.invalid`. No customer data is used.

The trusted host holds the database owner credential and a separate SELECT-only
verifier credential. Neither enters the snapshot, action token, broker configuration
or execution container. The coordinator signing key also stays outside execution.
Docker administrators can inspect the database container's environment; that is a
trusted development control-plane privilege, never granted to agent execution.

The demonstration then:

1. Reads a consistent database snapshot outside the sandbox, recording table
   existence, row counts and SHA-256 digests of ordered explicit columns.
2. Confirms the live database rejects a wrong password and rejects DELETE by the
   SELECT-only verifier. Confirms the exact database IP and port are reachable
   from a separate trusted bridge-network control container.
3. Requests a `DATABASE_OPERATION` through the deterministic policy service.
   The decision is DENY; token issuance fails and no execution is created.
4. Authorizes and executes a real patch correcting a synthetic shop total from
   addition to multiplication. A trusted provisioner advances the exact snapshot
   revision in the external policy; the agent cannot update its own policy.
5. Authorizes tests through the signed broker and real HTTP coordinator. Actual
   sandbox tests check the edited calculation and attempt bounded TCP connections
   to the protected database container and host-loopback service. They must fail.
   Additional checks cover privileged environment names and common credential/
   Docker socket mounts. The trusted broker records actual container configuration,
   including `NetworkMode=none` and no bind mounts.
6. Reads the protected tables again using the external verifier and requires
   complete, nonempty, identical before/after evidence. Saves a development report
   when an evidence directory is configured. Disposable protected containers are
   stopped and removed during fixture cleanup, including on assertion failure.

Separate regressions change a value without changing row counts, delete a row,
exceed the bounded fixture size and drop a table. The verifier must detect all
four conditions. Missing, empty or invalid evidence cannot satisfy the comparison.

## Reproduce locally

Use the existing `.venv-rs2`, cached `postgres:17` and restricted image documented
in [RESTRICTED_EXECUTION.md](RESTRICTED_EXECUTION.md). No image pull, paid service
or LLM is needed. Start a disposable coordinator PostgreSQL database as described
in [LOCAL_COORDINATOR.md](LOCAL_COORDINATOR.md), then set these PowerShell variables
in the trusted host terminal. Substitute that coordinator's disposable URL.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:REPOSHIELD_TEST_DATABASE_URL = '<disposable coordinator PostgreSQL SQLAlchemy URL>'
$env:REPOSHIELD_TEST_RUNNER_IMAGE = 'reposhield-restricted@sha256:d7fa14e9b41f25dbd10b7872c5dc8d85e3741c7e6a00d5b6b05a7e8f7502a66e'
$env:REPOSHIELD_TEST_PROTECTED_DATABASE = '1'
$env:REPOSHIELD_TEST_EVIDENCE_DIR = 'docs/evidence/rs2-07'
.venv-rs2/Scripts/python -u -m pytest tests/test_protected_database.py -q -ra
```

The protected database is provisioned by the opt-in fixture; do not supply a real
database. The coordinator fixture creates and drops only its own unique test
schema. To run all regressions, omit the test-file argument. Without opt-in or
required services, skipped integration tests are not acceptance evidence.

## Limits and next dependency

Policy DENY, wrong-password rejection and network isolation are distinct checks;
an allowlist is not treated as an execution boundary. Before/after digests prove
final equality of the selected table data, not the absence of transient writes,
database-wide schema changes, or all possible bypasses. Test observations can be
forged by malicious code; these fixed trusted fixtures and external database
observations are bounded development evidence, not a general proof of safety.

Reports are currently unsigned local artifacts. Authenticated retained evidence
belongs to RS2 08. No verification PASS is issued by this demonstration. Before
acceptance, repeat the RS2 06 isolation and lifecycle checks plus this demonstration
on a dedicated Linux host without personal mounts or platform credentials, and
complete the deferred verification-worker integration. RS2 08 is not implemented
by this phase.
