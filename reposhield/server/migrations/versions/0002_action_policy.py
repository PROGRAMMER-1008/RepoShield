"""Pinned session policy and separate immutable approvals."""
from alembic import op
from reposhield.server.schema_v2 import session_scopes, approvals

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    session_scopes.create(op.get_bind())
    approvals.create(op.get_bind())


def downgrade():
    approvals.drop(op.get_bind())
    session_scopes.drop(op.get_bind())
