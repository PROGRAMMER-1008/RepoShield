"""Immutable trusted evidence checkpoints; bundle copies outside DB are untrusted."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from .schema_v1 import ident, created, ID

metadata = sa.MetaData()  # Keep earlier migration metadata frozen.

checkpoints = sa.Table("evidence_checkpoints", metadata, ident(), created(),
    sa.Column("kind", sa.Text, nullable=False), sa.Column("subject_id", ID, nullable=False),
    sa.Column("context", JSONB, nullable=False), sa.Column("bundle_digest", sa.String(64), nullable=False),
    sa.Column("event_count", sa.Integer, nullable=False), sa.Column("event_head", sa.String(64), nullable=False),
    sa.Column("bundle", JSONB, nullable=False),
    sa.CheckConstraint("kind IN ('attempt', 'session') AND event_count > 0"))
