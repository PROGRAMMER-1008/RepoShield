"""Frozen migration 0003: one issued authorization per decision."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()
sa.Table("decisions", metadata, sa.Column("id", sa.String(64), primary_key=True))
authorizations = sa.Table("authorizations", metadata,
    sa.Column("decision_id", sa.String(64), sa.ForeignKey("decisions.id"), primary_key=True),
    sa.Column("token", JSONB, nullable=False))
