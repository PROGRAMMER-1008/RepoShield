"""Frozen additive schema for migration 0002."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()
# FK targets only; migration creates the two new tables explicitly.
sa.Table("sessions", metadata, sa.Column("id", sa.String(64), primary_key=True))
sa.Table("decisions", metadata, sa.Column("id", sa.String(64), primary_key=True))
session_scopes = sa.Table("session_scopes", metadata,
    sa.Column("session_id", sa.String(64), sa.ForeignKey("sessions.id"), primary_key=True),
    sa.Column("payload", JSONB, nullable=False))
approvals = sa.Table("approvals", metadata,
    sa.Column("decision_id", sa.String(64), sa.ForeignKey("decisions.id"), primary_key=True),
    sa.Column("actor_id", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("context_digest", sa.String(64), nullable=False))
