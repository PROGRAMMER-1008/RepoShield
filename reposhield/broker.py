"""Separate trusted broker. Public keys and broker credential only; never a signer."""
import argparse
import base64
import json
from pathlib import Path
import time
import urllib.request
import urllib.parse

from .authorization import verify_token, load_public_keys
from .snapshots import SnapshotStore, decode_snapshot, apply_patch
from .restricted_runner import RestrictedRunner, RunnerFailure


class CoordinatorClient:
    def __init__(self, url, credential):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")):
            raise ValueError("coordinator requires HTTPS or loopback")
        self.url, self.credential = url.rstrip("/"), credential

    def call(self, path, data=None):
        raw = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.url + path, raw,
              {"Authorization": "Bearer " + self.credential, "Content-Type": "application/json"})
        # Never retry a claim whose response may have been lost. No redirects to another origin.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs): return None
        with urllib.request.build_opener(NoRedirect).open(req, timeout=5) as response:
            data = response.read(1048577)
        if len(data) > 1048576: raise ValueError("coordinator response too large")
        return json.loads(data)


class Broker:
    def __init__(self, store, runner, client, keys, audience, resources):
        self.store, self.runner, self.client = store, runner, client
        self.keys, self.audience, self.resources = keys, audience, resources

    def execute(self, value):
        token = verify_token(value, self.keys, audience=self.audience, now=int(time.time()))
        p = token.payload
        if self.resources.get(p.resource_id) != {"tenant_id": p.request.tenant_id, "repository_id": p.request.repository_id}:
            raise ValueError("resource not registered at executor")
        files = self.store.get(p.request.workspace_revision)
        kind = p.request.action.action_type
        if kind not in ("READ_FILE", "APPLY_PATCH", "RUN_TESTS"):
            raise ValueError("unsupported action")
        # No side effects or candidate code before a successful coordinator claim.
        self.runner.preflight(p.profile)
        claim = self.client.call("/api/v1/actions/claim", {
            "authorization": token.model_dump(mode="json"), "request": p.request.model_dump(mode="json"),
            "resource_id": p.resource_id, "profile": p.profile.model_dump(mode="json")})
        import re
        if claim.get("state") != "unknown-outcome" or not re.fullmatch(r"[0-9a-f]{32}", claim.get("execution_id", "")):
            raise ValueError("invalid claim response")
        execution_id = claim["execution_id"]
        def active():
            return self.client.call(f"/api/v1/executions/{execution_id}/status").get("active") is True
        state, outcome = "failed-infrastructure", {}
        try:
            if not active(): raise RunnerFailure("session_inactive")
            if kind == "READ_FILE":
                data = files[p.request.action.path]
                if len(data) > min(p.request.action.max_bytes, p.profile.output_bytes // 2):
                    raise RunnerFailure("read_limit")
                outcome = {"content_base64": base64.b64encode(data).decode(), "source_revision": p.request.workspace_revision}
            elif kind == "APPLY_PATCH":
                updated = apply_patch(files, p.request.action.patch)
                if not active(): raise RunnerFailure("session_inactive")
                outcome = {"source_revision": p.request.workspace_revision, "new_revision": self.store.put(updated)}
            else:
                paths = list(p.request.action.test_paths)
                if any(path not in files for path in paths): raise RunnerFailure("test_path_missing")
                outcome = self.runner.run(files, paths, p.profile, active)
            if not active(): raise RunnerFailure("session_inactive")
            state = "completed"
        except Exception as error:
            code = str(error) if isinstance(error, RunnerFailure) else type(error).__name__
            outcome = {"error": code[:120]}
            state = "cancelled" if code == "session_inactive" else "failed-infrastructure"
        outcome["mode"] = "DEVELOPMENT EXECUTION" if self.runner.development_desktop else "CONTROLLED SESSION"
        if len(json.dumps(outcome).encode()) > 240 * 1024:
            state, outcome = "failed-infrastructure", {"error": "result_limit", "mode": outcome["mode"]}
        # A failed terminal report leaves unknown-outcome; do not retry execution.
        recorded = self.client.call(f"/api/v1/executions/{execution_id}/result", {"state": state, "outcome": outcome})
        if recorded.get("state") != state:
            state = recorded["state"]
            outcome = {"error": "context_changed_before_completion", "mode": outcome["mode"]}
        return {"execution_id": execution_id, "state": state, "outcome": outcome}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Restricted RepoShield broker (separate trusted execution host)")
    parser.add_argument("--config", required=True)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--development-desktop", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.config).resolve()
    if path.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("broker configuration must be outside RepoShield source")
    def read_json(file, limit):
        with Path(file).open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit: raise ValueError("broker input too large")
        return json.loads(data)
    config = read_json(path, 65536)
    token = read_json(args.authorization, 1048576)
    broker = Broker(SnapshotStore(config["snapshot_store"]), RestrictedRunner(development_desktop=args.development_desktop),
                    CoordinatorClient(config["coordinator_url"], config["credential"]),
                    load_public_keys(config["verification_keys_file"], [config["snapshot_store"]]),
                    config["audience"], config["resources"])
    result = broker.execute(token)
    print(json.dumps(result))
    return 0 if result["state"] == "completed" and result["outcome"].get("mandatory_evidence_satisfied", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
