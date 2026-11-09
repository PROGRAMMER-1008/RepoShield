"""GitHub installation, durable webhook intake and Checks outbox."""
from alembic import op
from reposhield.server.schema_v5 import installations, deliveries, checks

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    for table in (installations, deliveries, checks): table.create(op.get_bind())


def downgrade():
    for table in (checks, deliveries, installations): table.drop(op.get_bind())
