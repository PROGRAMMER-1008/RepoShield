"""Durable GitHub intake and publication. External side effects never run in agents."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from fastapi import HTTPException

from .github import verify_signature, HANDLED_ACTIONS
from .github_app import AppClient, load_config, external_bytes, fetch_public, GitHubError, AccessRevoked
from .schema_v1 import repositories, runs, attempts, outbox
from .schema_v5 import installations, deliveries, checks
from .evidence_service import EvidenceService
from .identities import Identity

CHECK_NAME = "RepoShield / verification"


class GitHubService:
    def __init__(self, store, cfg, client=None, fetcher=None):
        self.store, self.cfg = store, cfg
        with store.engine.connect() as c:
            self.roots = [*c.scalars(sa.select(repositories.c.path)).all(), str(Path(__file__).resolve().parents[2])]
        self.config = load_config(cfg.github_app_config_file, self.roots)
        self.client = client or AppClient(self.config, self.roots)
        self.fetcher = fetcher or fetch_public
        self.evidence = EvidenceService(store, cfg)

    def onboard(self):
        self.client.installation_token()  # Verify App, installation, permissions and exact public repository.
        cfg = self.config
        with self.store.engine.begin() as c:
            repo = c.execute(sa.select(repositories).where(repositories.c.id == cfg.repository_id).with_for_update()).mappings().first()
            if repo is None: raise ValueError("register the administrator-owned repository first")
            old = c.execute(sa.select(installations).where(installations.c.repository_id == cfg.repository_id)).mappings().first()
            if old and (old["remote_repository_id"] != cfg.remote_repository_id or old["full_name"].lower() != cfg.full_name.lower()):
                raise ValueError("repository remapping requires separate registration")
            values = dict(repository_id=cfg.repository_id, installation_id=cfg.installation_id,
                          remote_repository_id=cfg.remote_repository_id, full_name=cfg.full_name, enabled=True)
            c.execute(insert(installations).values(**values).on_conflict_do_update(index_elements=["repository_id"], set_=values))
        return {"repository_id": cfg.repository_id, "installation_id": cfg.installation_id, "enabled": True}

    def binding(self, c, lock=False):
        query = sa.select(installations).where(installations.c.repository_id == self.config.repository_id)
        row = c.execute(query.with_for_update() if lock else query).mappings().first()
        if (row is None or row["installation_id"] != self.config.installation_id
                or row["remote_repository_id"] != self.config.remote_repository_id
                or row["full_name"] != self.config.full_name):
            raise AccessRevoked("repository_not_onboarded")
        return row

    def receive(self, delivery_id, event, signature, raw):
        if len(raw) > 1048576: raise HTTPException(413, "webhook too large")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", delivery_id or ""):
            raise HTTPException(422, "invalid delivery ID")
        secret = external_bytes(self.config.webhook_secret_file, self.roots, 4096).decode().strip()
        if (len(secret) < 32 or not re.fullmatch(r"sha256=[0-9a-f]{64}", signature or "")
                or not verify_signature(secret, raw, signature)):
            raise HTTPException(401, "invalid webhook signature")
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict): raise ValueError()
            if event == "ping":
                return {"duplicate": False, "state": "ignored"}  # Signed handshake; no scheduling or installation change.
            iid = payload["installation"]["id"]
            if type(iid) is not int or iid != self.config.installation_id: raise ValueError()
            action = payload.get("action", "")
            if not isinstance(action, str) or len(action) > 64: raise ValueError()
        except (ValueError, KeyError, TypeError): raise HTTPException(422, "invalid webhook context") from None
        body_digest = hashlib.sha256(raw).hexdigest()
        with self.store.engine.begin() as c:
            mapping = self.binding(c, lock=True)
            previous = c.execute(sa.select(deliveries).where(deliveries.c.id == delivery_id)).mappings().first()
            if previous:
                if previous["body_digest"] != body_digest or previous["event"] != event:
                    raise HTTPException(409, "delivery ID reused with different content")
                return {"duplicate": True, "state": previous["state"]}
            revoke = event == "installation" and action in ("deleted", "suspend")
            if event == "installation_repositories" and action == "removed":
                removed = payload.get("repositories_removed", [])
                if not isinstance(removed, list): raise HTTPException(422, "invalid removal event")
                revoke = any(isinstance(r, dict) and r.get("id") == self.config.remote_repository_id for r in removed)
            number, state = None, "ignored"
            if revoke:
                c.execute(installations.update().where(installations.c.repository_id == mapping["repository_id"]).values(enabled=False))
                state = "processed"
            elif event == "pull_request" and action in HANDLED_ACTIONS:
                try:
                    number = payload["pull_request"]["number"]
                    if (type(number) is not int or number <= 0 or payload["repository"]["id"] != mapping["remote_repository_id"]):
                        raise ValueError()
                except (KeyError, TypeError, ValueError): raise HTTPException(422, "invalid repository or PR") from None
                if not mapping["enabled"]: raise HTTPException(403, "installation disabled")
                state = "pending"
            # Receipt and bounded durable intake intent are the same transactional row.
            c.execute(deliveries.insert().values(id=delivery_id, repository_id=mapping["repository_id"],
                body_digest=body_digest, event=event[:64], action=action, pr_number=number, state=state))
            return {"duplicate": False, "state": state}

    def _intake(self, c, delivery, token):
        pr = self.client.pull(delivery["pr_number"], token)  # Current API state, never the event's claimed head.
        if pr.get("state") != "open":
            c.execute(deliveries.update().where(deliveries.c.id == delivery["id"]).values(state="ignored"))
            return
        repo = c.execute(sa.select(repositories).where(repositories.c.id == delivery["repository_id"]).with_for_update()).mappings().one()
        if repo["base_sha"] != pr["base"]["sha"]:
            raise GitHubError("trusted_base_changed_reactivation_required")
        merge_base = self.fetcher(repo, self.config, pr)
        source = dict(installation_id=self.config.installation_id, remote_repository_id=self.config.remote_repository_id,
            pr_number=pr["number"], base_tip=pr["base"]["sha"], head_sha=pr["head"]["sha"], merge_base=merge_base,
            execution_tree=pr["head"]["sha"], strategy="head-only-require-up-to-date-branch")
        job = self.store.enqueue(repo["id"], pr["head"]["sha"], "github-app", connection=c, source_context=source)
        c.execute(insert(checks).values(attempt_id=job["attempt_id"], repository_id=repo["id"], pr_number=pr["number"],
            head_sha=pr["head"]["sha"], base_sha=pr["base"]["sha"]).on_conflict_do_nothing(index_elements=["attempt_id"]))
        c.execute(deliveries.update().where(deliveries.c.id == delivery["id"]).values(state="processed", attempt_id=job["attempt_id"]))

    def _check(self, row, token):
        external_id = "reposhield:" + row["attempt_id"]
        prefix = f"/repos/{self.config.full_name}"
        matches = []
        for page in range(1, 4):
            data = self.client.call("GET", f"{prefix}/commits/{row['head_sha']}/check-runs?filter=all&per_page=100&page={page}", token)
            items = data.get("check_runs")
            if not isinstance(items, list): raise GitHubError("invalid_check_list")
            matches.extend(r for r in items if r.get("external_id") == external_id and r.get("app", {}).get("id") == self.config.app_id)
            if len(items) < 100: break
        else: raise GitHubError("check_reconciliation_limit")
        if len(matches) > 1: raise GitHubError("duplicate_remote_checks_require_reconciliation")
        if not matches:
            check = self.client.call("POST", prefix + "/check-runs", token,
                {"name": CHECK_NAME, "head_sha": row["head_sha"], "external_id": external_id, "status": "queued"})
        else:
            check = matches[0]
        if (type(check.get("id")) is not int or check["id"] <= 0 or check.get("head_sha") != row["head_sha"]
                or check.get("external_id") != external_id or check.get("name") != CHECK_NAME
                or check.get("app", {}).get("id") != self.config.app_id):
            raise GitHubError("remote_check_identity_mismatch")
        return check["id"]

    def _publish(self, c, row, token):
        pr = self.client.pull(row["pr_number"], token)
        if pr.get("state") != "open" or pr["head"]["sha"] != row["head_sha"] or pr["base"]["sha"] != row["base_sha"]:
            c.execute(checks.update().where(checks.c.attempt_id == row["attempt_id"]).values(state="obsolete"))
            return
        check_id = self._check(row, token)
        c.execute(checks.update().where(checks.c.attempt_id == row["attempt_id"]).values(check_id=check_id))
        attempt = c.execute(sa.select(attempts, runs.c.inputs).join(runs).where(attempts.c.id == row["attempt_id"])).mappings().one()
        if attempt["state"] in ("queued", "running"):
            c.execute(checks.update().where(checks.c.attempt_id == row["attempt_id"]).values(available_at=sa.func.now() + timedelta(seconds=2)))
            return
        repo = c.execute(sa.select(repositories).where(repositories.c.id == row["repository_id"]).with_for_update()).mappings().one()
        publisher = Identity(id="github-publisher", tenant_id=repo["tenant_id"], role="administrator",
                             repository_ids=(repo["id"],), token_sha256="0" * 64)
        checkpoint_id = row["checkpoint_id"]
        if checkpoint_id is None:
            checkpoint_id = self.evidence.seal("attempt", row["attempt_id"], publisher)["checkpoint_id"]
            c.execute(checks.update().where(checks.c.attempt_id == row["attempt_id"]).values(checkpoint_id=checkpoint_id))
        replay = self.evidence.replay(checkpoint_id, publisher)
        if replay["context"]["subject_id"] != row["attempt_id"] or replay["context"]["inputs"] != attempt["inputs"]:
            raise GitHubError("evidence_context_mismatch")
        result = replay["artifacts"].get("result") or {}
        conclusion, title = "failure", "Infrastructure failure"
        if attempt["state"] == "completed":
            verdict = result.get("verdict")
            if verdict == "BLOCK": title = "BLOCK: policy or verification failed"
            elif verdict == "REVIEW_REQUIRED": title = "REVIEW_REQUIRED: unresolved evidence or review"
            elif verdict == "PASS":
                eligible = self.evidence.cache_eligibility(checkpoint_id, publisher, attempt["inputs"])["cache_eligible"]
                if eligible: conclusion, title = "success", "PASS: authenticated static verification; no tests required"
                else: title = "REVIEW_REQUIRED: PASS lacks eligible trusted evidence"
        elif attempt["state"] == "cancelled": title = "Verification cancelled"
        # Final fresh API read narrows races; updates remain tied to this immutable head.
        current = self.client.pull(row["pr_number"], token)
        if current.get("state") != "open" or current["head"]["sha"] != row["head_sha"] or current["base"]["sha"] != row["base_sha"]:
            c.execute(checks.update().where(checks.c.attempt_id == row["attempt_id"]).values(state="obsolete"))
            return
        remote = self.client.call("GET", f"/repos/{self.config.full_name}/check-runs/{check_id}", token)
        if (remote.get("head_sha") != row["head_sha"] or remote.get("external_id") != "reposhield:" + row["attempt_id"]
                or remote.get("app", {}).get("id") != self.config.app_id):
            raise GitHubError("remote_check_identity_mismatch")
        self.client.call("PATCH", f"/repos/{self.config.full_name}/check-runs/{check_id}", token,
            {"status": "completed", "conclusion": conclusion, "output": {"title": title,
             "summary": f"Head-only verification for {row['head_sha']}. Evidence checkpoint {checkpoint_id}. "
                        "Dynamic execution integration and dedicated-host acceptance remain pending."}})
        c.execute(checks.update().where(checks.c.attempt_id == row["attempt_id"]).values(state="published"))
        c.execute(outbox.update().where(outbox.c.attempt_id == row["attempt_id"], outbox.c.kind == "verification.completed")
                  .values(state="published"))

    def run_once(self, publishing=False):
        table, key = (checks, "attempt_id") if publishing else (deliveries, "id")
        selected = None
        try:
            with self.store.engine.begin() as c:
                row = c.execute(sa.select(table).where(table.c.repository_id == self.config.repository_id,
                    table.c.state == "pending", table.c.available_at <= sa.func.now(), table.c.tries < 5)
                    .order_by(table.c.created_at, table.c[key]).with_for_update(skip_locked=True).limit(1)).mappings().first()
                if row is None: return False
                selected = row[key]
                if not self.binding(c, lock=True)["enabled"]: raise AccessRevoked("installation_disabled")
                token = self.client.installation_token()  # Fresh scoped token; never persisted or cached across jobs.
                (self._publish if publishing else self._intake)(c, row, token)
            return True
        except Exception as error:
            if selected is None: raise
            with self.store.engine.begin() as c:
                row = c.execute(sa.select(table).where(table.c[key] == selected,
                    table.c.state == "pending").with_for_update()).mappings().first()
                if row is None: return True  # Another worker already finalized after rollback.
                count = row["tries"] + 1
                c.execute(table.update().where(table.c[key] == selected).values(tries=count,
                    state="failed" if count >= 5 or isinstance(error, AccessRevoked) else "pending",
                    available_at=sa.func.now() + timedelta(seconds=min(60, 2 ** count)),
                    error=str(error)[:120] if isinstance(error, GitHubError) else type(error).__name__))
                if isinstance(error, AccessRevoked):
                    c.execute(installations.update().where(installations.c.repository_id == self.config.repository_id).values(enabled=False))
            return True
