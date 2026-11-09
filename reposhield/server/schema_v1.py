"""Frozen SQLAlchemy schema for migration 0001 (do not edit after release)."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()
ID = sa.String(64)
STAMP = sa.DateTime(timezone=True)


def ident():
    return sa.Column("id", ID, primary_key=True)


def created():
    return sa.Column("created_at", STAMP, nullable=False, server_default=sa.func.now())


repositories = sa.Table("repositories", metadata, ident(), created(),
    sa.Column("tenant_id", ID, nullable=False), sa.Column("name", sa.Text, nullable=False),
    sa.Column("path", sa.Text, nullable=False), sa.Column("base_sha", sa.String(40), nullable=False),
    sa.Column("policy_epoch", sa.Integer, nullable=False, server_default="1"),
    sa.UniqueConstraint("tenant_id", "name"))
runs = sa.Table("runs", metadata, ident(), created(),
    sa.Column("repository_id", ID, sa.ForeignKey("repositories.id"), nullable=False),
    sa.Column("input_digest", sa.String(64), nullable=False),
    sa.Column("inputs", JSONB, nullable=False),
    sa.UniqueConstraint("repository_id", "input_digest"))
attempts = sa.Table("attempts", metadata, ident(), created(),
    sa.Column("run_id", ID, sa.ForeignKey("runs.id"), nullable=False),
    sa.Column("request_key", ID, nullable=False), sa.Column("requested_by", ID, nullable=False),
    sa.Column("state", sa.Text, nullable=False, server_default="queued"),
    sa.Column("finished_at", STAMP), sa.Column("result", JSONB),
    sa.CheckConstraint("state IN ('queued','running','completed','failed-infrastructure','cancelled')"),
    sa.UniqueConstraint("run_id", "request_key"))
tasks = sa.Table("tasks", metadata, ident(), created(),
    sa.Column("attempt_id", ID, sa.ForeignKey("attempts.id"), nullable=False),
    sa.Column("stage", sa.Text, nullable=False),
    sa.Column("state", sa.Text, nullable=False, server_default="queued"),
    sa.Column("tries", sa.Integer, nullable=False, server_default="0"),
    sa.Column("max_tries", sa.Integer, nullable=False, server_default="3"),
    sa.Column("available_at", STAMP, nullable=False, server_default=sa.func.now()),
    sa.Column("lease_owner", ID), sa.Column("lease_epoch", sa.Integer, nullable=False, server_default="0"),
    sa.Column("lease_until", STAMP), sa.Column("output", JSONB), sa.Column("error", sa.Text),
    sa.CheckConstraint("stage IN ('snapshot','analyze','tests','aggregate','publish')"),
    sa.CheckConstraint("state IN ('queued','running','succeeded','failed','cancelled')"),
    sa.CheckConstraint("tries >= 0 AND max_tries BETWEEN 1 AND 5 AND lease_epoch >= 0"),
    sa.UniqueConstraint("attempt_id", "stage"))
sa.Index("tasks_ready", tasks.c.state, tasks.c.available_at)
dependencies = sa.Table("task_dependencies", metadata,
    sa.Column("task_id", ID, sa.ForeignKey("tasks.id"), primary_key=True),
    sa.Column("depends_on", ID, sa.ForeignKey("tasks.id"), primary_key=True),
    sa.CheckConstraint("task_id <> depends_on"))
sessions = sa.Table("sessions", metadata, ident(), created(),
    sa.Column("repository_id", ID, sa.ForeignKey("repositories.id"), nullable=False),
    sa.Column("owner_id", ID, nullable=False),
    sa.Column("state", sa.Text, nullable=False, server_default="active"),
    sa.Column("expires_at", STAMP, nullable=False),
    sa.Column("revocation_epoch", sa.Integer, nullable=False, server_default="0"),
    sa.CheckConstraint("state IN ('active','revoked')"))
action_requests = sa.Table("action_requests", metadata, ident(), created(),
    sa.Column("session_id", ID, sa.ForeignKey("sessions.id"), nullable=False),
    sa.Column("action_digest", sa.String(64), nullable=False), sa.Column("payload", JSONB, nullable=False))
decisions = sa.Table("decisions", metadata, ident(), created(),
    sa.Column("action_request_id", ID, sa.ForeignKey("action_requests.id"), nullable=False),
    sa.Column("decision", sa.Text, nullable=False), sa.Column("policy_digest", sa.String(64), nullable=False),
    sa.Column("policy_epoch", sa.Integer, nullable=False), sa.Column("expires_at", STAMP),
    sa.Column("nonce", ID, unique=True), sa.Column("payload", JSONB, nullable=False),
    sa.CheckConstraint("decision IN ('ALLOW','DENY','REVIEW_REQUIRED')"))
executions = sa.Table("executions", metadata, ident(), created(),
    sa.Column("decision_id", ID, sa.ForeignKey("decisions.id"), nullable=False, unique=True),
    sa.Column("state", sa.Text, nullable=False), sa.Column("outcome", JSONB),
    sa.CheckConstraint("state IN ('queued','running','completed','failed-infrastructure','cancelled','unknown-outcome')"))
events = sa.Table("events", metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True), created(),
    sa.Column("attempt_id", ID, sa.ForeignKey("attempts.id")),
    sa.Column("session_id", ID, sa.ForeignKey("sessions.id")),
    sa.Column("actor_id", ID, nullable=False), sa.Column("kind", sa.Text, nullable=False),
    sa.Column("data", JSONB, nullable=False))
outbox = sa.Table("outbox", metadata, ident(), created(),
    sa.Column("attempt_id", ID, sa.ForeignKey("attempts.id"), nullable=False),
    sa.Column("kind", sa.Text, nullable=False), sa.Column("payload", JSONB, nullable=False),
    sa.Column("state", sa.Text, nullable=False, server_default="pending"),
    sa.Column("tries", sa.Integer, nullable=False, server_default="0"),
    sa.Column("available_at", STAMP, nullable=False, server_default=sa.func.now()),
    sa.UniqueConstraint("attempt_id", "kind"),
    sa.CheckConstraint("state IN ('pending','publishing','published','failed')"))
