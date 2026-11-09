"""Persist immutable signed authorizations."""
from alembic import op
from reposhield.server.schema_v3 import authorizations

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    authorizations.create(op.get_bind())


def downgrade():
    authorizations.drop(op.get_bind())
