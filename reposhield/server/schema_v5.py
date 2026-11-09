"""Frozen additive GitHub intake and publication schema."""
import sqlalchemy as sa
from .schema_v1 import ID, created

metadata = sa.MetaData()
sa.Table("repositories", metadata, sa.Column("id", ID, primary_key=True))
sa.Table("attempts", metadata, sa.Column("id", ID, primary_key=True))
installations = sa.Table("github_installations", metadata,
    sa.Column("repository_id", ID, sa.ForeignKey("repositories.id"), primary_key=True),
    sa.Column("installation_id", sa.BigInteger, nullable=False),
    sa.Column("remote_repository_id", sa.BigInteger, nullable=False, unique=True),
    sa.Column("full_name", sa.Text, nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()))
deliveries = sa.Table("github_deliveries", metadata,
    sa.Column("id", sa.String(128), primary_key=True), created(),
    sa.Column("repository_id", ID, sa.ForeignKey("repositories.id"), nullable=False),
    sa.Column("body_digest", sa.String(64), nullable=False),
    sa.Column("event", sa.Text, nullable=False), sa.Column("action", sa.Text, nullable=False),
    sa.Column("pr_number", sa.Integer), sa.Column("attempt_id", ID, sa.ForeignKey("attempts.id")),
    sa.Column("state", sa.Text, nullable=False, server_default="pending"),
    sa.Column("tries", sa.Integer, nullable=False, server_default="0"),
    sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("error", sa.Text),
    sa.CheckConstraint("state IN ('pending','processed','ignored','failed')"))
checks = sa.Table("github_checks", metadata,
    sa.Column("attempt_id", ID, sa.ForeignKey("attempts.id"), primary_key=True), created(),
    sa.Column("repository_id", ID, sa.ForeignKey("repositories.id"), nullable=False),
    sa.Column("pr_number", sa.Integer, nullable=False),
    sa.Column("head_sha", sa.String(40), nullable=False), sa.Column("base_sha", sa.String(40), nullable=False),
    sa.Column("check_id", sa.BigInteger), sa.Column("checkpoint_id", ID),
    sa.Column("state", sa.Text, nullable=False, server_default="pending"),
    sa.Column("tries", sa.Integer, nullable=False, server_default="0"),
    sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("error", sa.Text),
    sa.CheckConstraint("state IN ('pending','published','obsolete','failed')"))
