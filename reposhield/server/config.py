from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ServerConfig:
    data_dir: str = "reposhield-data"
    host: str = "127.0.0.1"
    port: int = 8080
    workers: int = 2
    sandbox: str = "auto"
    api_token: str | None = field(default_factory=lambda: os.environ.get("REPOSHIELD_API_TOKEN"))
    webhook_secret: str | None = field(default_factory=lambda: os.environ.get("GITHUB_WEBHOOK_SECRET"))
    github_token: str | None = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN"))
    allowed_repos: list = field(default_factory=list)       # "owner/name" or "*"  (webhook allow-list; empty = reject all)
    local_roots: list = field(default_factory=list)         # directories under which local repos may be verified
    public_url: str | None = None
    insecure_dev_sandbox: bool = False                      # allow running webhook-submitted code without an isolating sandbox
    database_url: str | None = field(default_factory=lambda: os.environ.get("REPOSHIELD_DATABASE_URL"))
    identities_file: str | None = field(default_factory=lambda: os.environ.get("REPOSHIELD_IDENTITIES_FILE"))
    action_policy_file: str | None = field(default_factory=lambda: os.environ.get("REPOSHIELD_ACTION_POLICY_FILE"))
    signing_key_file: str | None = field(default_factory=lambda: os.environ.get("REPOSHIELD_SIGNING_KEY_FILE"))
    signing_key_id: str | None = field(default_factory=lambda: os.environ.get("REPOSHIELD_SIGNING_KEY_ID"))
    verification_keys_file: str | None = field(default_factory=lambda: os.environ.get("REPOSHIELD_VERIFICATION_KEYS_FILE"))
    executor_identities_file: str | None = field(default_factory=lambda: os.environ.get("REPOSHIELD_EXECUTOR_IDENTITIES_FILE"))
    github_app_config_file: str | None = field(default_factory=lambda: os.environ.get("REPOSHIELD_GITHUB_APP_CONFIG_FILE"))
    ui_config_file: str | None = field(default_factory=lambda: os.environ.get("REPOSHIELD_UI_CONFIG_FILE"))

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "reposhield.db")

    @property
    def repos_dir(self) -> str:
        return os.path.join(self.data_dir, "repos")
