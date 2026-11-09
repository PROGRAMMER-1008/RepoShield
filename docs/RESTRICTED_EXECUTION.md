# Restricted execution development slice (RS2 06)

**Dedicated Linux VM acceptance remains pending.** The user authorized Docker
Desktop development validation on 11 October 2026. Docker Desktop has personal-host
integration and is not represented as the isolated deployment required by the plan.
The broker requires `--development-desktop` here and labels results DEVELOPMENT
EXECUTION. Default mode rejects Windows brokers and Desktop daemons. On Linux,
passing that check does not prove host dedication: the administrator must establish
and validate separate infrastructure with no personal folders or privileged routes.

## Implemented boundary

`python -m reposhield.broker` is a separate trusted process, never an API-host worker.
It takes public verification keys, an executor credential, named resource mappings
and a snapshot store. It does not receive private signing keys or database credentials.
It verifies the signed request and immutable snapshot, checks the local image,
obtains one coordinator claim, then performs the exact typed operation.

- READ_FILE reads bounded bytes from the hashed snapshot, not an arbitrary host path.
- APPLY_PATCH applies the narrow unified format with exact context/position checks,
  stores a new content-addressed snapshot and retains the old one. A new revision
  needs trusted policy activation and a new decision before subsequent execution.
- RUN_TESTS streams snapshot bytes through stdin to a fresh Linux container. No host
  source, output directory, credential, socket or configuration is mounted.

Snapshots are canonical JSON containing base64 regular-file bytes, limited to 1000
files and 8 MiB encoded. Paths reject traversal, absolute paths, dotfiles and device
names. They contain no links, file modes or archive extraction instructions. Every
read verifies the SHA-256 identity. The broker store is administrator-owned and must
be inaccessible to agents. Candidate modifications inside a test container affect
only its private copy; no test-produced source snapshot is imported automatically.

Only the trusted provisioner imports snapshots. For a small explicit input set:

```python
from pathlib import Path
from reposhield.snapshots import SnapshotStore
store = SnapshotStore("/srv/reposhield/snapshots")
revision = store.put({
    "src/app.py": Path("trusted-export/src/app.py").read_bytes(),
    "tests/test_app.py": Path("trusted-export/tests/test_app.py").read_bytes(),
})
print(revision)
```

This identity covers these exact files; it is not an attestation that an entire Git
commit was exported. Git export/onboarding automation remains unfinished. Never
let an agent choose the administrator's import paths or write the snapshot store.

## Runner image and enforced development settings

The tested restricted image is built with `runner/Dockerfile.restricted`; the legacy
verification image remains in `runner/Dockerfile`. The new build context is limited
by `runner/.dockerignore`. A registry DNS failure prevented downloading a new slim
base. The successful offline build used the cached prototype base with Python
3.12.15 and pytest 9.1.1, with its identity recorded in the evidence. No candidate
dependency or build script was executed during image preparation.

```powershell
docker build --network none --pull=false --build-arg BASE=reposhield-runner:py312 -f runner/Dockerfile.restricted -t reposhield-restricted:rs206 runner
docker image inspect reposhield-restricted:rs206 --format '{{.Id}}'
```

Check the administrator-prepared base identity before building. Set the signed
profile's `image` to `reposhield-restricted@` followed by the inspected `sha256:...`
ID. This adapter pins the **local Docker image ID**, not a mutable tag and not an
assumed registry manifest. It resolves the suffix locally, checks the inspected ID
and never pulls during execution. Missing images deny before claim. Do not copy an
illustrative digest from older setup examples.

The sandbox is non-root with no capabilities, default seccomp, no-new-privileges,
network none and read-only root. Signed memory/CPU/PID limits and swap equal to
memory are configured. `/work` is a size-limited noexec/nosuid/nodev tmpfs; `/tmp`
and HOME point there. Shared memory has a separate 64 KiB cap. No bind mounts,
anonymous image volumes, inherited broker environment or Docker log files are
allowed. Image environment variable names are restricted. Stdout and test reports
are bounded; the complete coordinator outcome is additionally limited to 240 KiB.

The broker's independent timer removes timed-out containers, including descendants.
Authorization is polled during execution; revocation, changed context, control-plane
failure or a stalled control channel cancels the container. Removal occurs in a
finally block on ordinary exceptions and interrupts; cleanup failures are errors.
Docker control operations have finite timeouts. Runtime includes cleanup latency.
Run `python -m reposhield.runner_watchdog` as an independently supervised trusted
process on the execution host. It checks once a second and removes only expired
containers with this runner's label and exact generated name shape. Deadlines are
attached before start. The watchdog does not retry actions or assign outcomes.
Its deployment/availability must be validated on the dedicated VM; without it,
an abruptly killed broker can leave a container running until manual cleanup.

Reference semantics: [Docker resource/runtime controls](https://docs.docker.com/engine/containers/run/)
and [tmpfs options and limitations](https://docs.docker.com/engine/storage/tmpfs/).
The saved container inspection and in-container probes are the local validation,
not the command line alone.

If the snapshot contains `requirements.txt`, preparation runs inside this same
restricted container using `pip --no-index --no-deps --only-binary=:all:` and
snapshot-supplied files under `wheels/`. Dependencies install only into `/work/deps`.
The signed snapshot therefore binds dependency bytes as well as tests. Supply all
needed wheels explicitly; network fetches and automatic transitive downloads are
unavailable. Missing dependencies remain non-successful. Candidate dependency code
never runs in the administrator's image build or broker environment. This is a
bounded offline subset, not a general package acquisition service.

## Coordinator and broker setup

Use the signing and separate executor identity setup in SIGNED_AUTHORIZATION.md.
The broker config must be external to RepoShield source and inaccessible to agents:

```json
{
  "coordinator_url": "https://trusted-coordinator.example",
  "credential": "executor-only-bearer-token",
  "audience": "broker",
  "verification_keys_file": "/etc/reposhield/public-keys.json",
  "snapshot_store": "/srv/reposhield/snapshots",
  "resources": {"source": {"tenant_id": "tenant", "repository_id": "repo"}}
}
```

HTTPS is required except loopback development. Claim calls do not retry or follow
redirects. Run the trusted broker outside the candidate environment:

```powershell
python -m reposhield.broker --config C:/trusted/broker.json --authorization C:/trusted/action-token.json --development-desktop
```

Do not provide this config, executor credential, source-store access or the broker's
Docker access to the connected agent. Agents submit typed requests through the
coordinator; the trusted operator dispatches the resulting token to the broker.
An unrestricted desktop agent that can ignore this path remains outside the boundary.

`GET /api/v1/executions/{id}/status` and `POST .../{id}/result` require the claiming
executor's scoped identity. Terminal results are immutable and separate from policy
decisions. Completed after stale/revoked context becomes cancelled. The API-host
`/actions/execute` route stays disabled; execution happens only in the broker.

For tests, completed means pytest finished. `mandatory_evidence_satisfied` is true
only with ordinary passing observations for every requested file and no failures.
A trusted pytest observer loads before candidate import paths to distinguish
ordinary passes from XPASS; JUnit alone is insufficient. All-skipped, all-XFAIL,
XPASS-only, empty collection, errors and missing reports are non-successful. The
broker CLI returns nonzero for missing mandatory test evidence. This does not create
a verification PASS: the existing verification worker remains static-only pending
integration with a validated execution environment. XML/stdout are hostile
observations; malicious test code may forge its own report. Signing later evidence
cannot make such observations semantically trustworthy.

## Remaining acceptance work

Run the broker on a dedicated Linux VM without host integration, shared folders,
platform credentials or unrestricted routes to protected services. Repeat all
isolation/resource tests there and independently verify that topology. The user
explicitly deferred that validation; it is the primary RS2 06 blocker.

Verification-worker integration remains gated on that validated execution host;
the current worker keeps missing dynamic evidence non-successful. Deploy and
supervise the independent watchdog and validate daemon/reboot failure handling.
The durable claim stays unknown-outcome after broker death and must never be replayed.
The administrator can inspect only this runner's jobs with:
`docker ps -a --filter label=reposhield.restricted=true` and remove identified orphan
IDs after investigation. Do not blanket-delete other containers.

RS2 07's [protected synthetic database demonstration](PROTECTED_DATABASE_DEMO.md)
now runs on Docker Desktop, including external before/after data verification.
Dedicated-host acceptance remains pending. No claim is made that local container
tests prove protection against arbitrary hostile code.
