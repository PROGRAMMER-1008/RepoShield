"""Trusted immutable evidence checkpoints."""
from alembic import op
from reposhield.server.schema_v4 import checkpoints

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    checkpoints.create(op.get_bind())
    op.execute("""CREATE FUNCTION reposhield_checkpoint_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'evidence checkpoints are immutable'; END; $$""")
    op.execute("""CREATE TRIGGER evidence_checkpoint_immutable BEFORE UPDATE OR DELETE ON evidence_checkpoints
        FOR EACH ROW EXECUTE FUNCTION reposhield_checkpoint_immutable()""")
    op.execute("""CREATE TRIGGER evidence_checkpoint_no_truncate BEFORE TRUNCATE ON evidence_checkpoints
        FOR EACH STATEMENT EXECUTE FUNCTION reposhield_checkpoint_immutable()""")


def downgrade():
    checkpoints.drop(op.get_bind())
    op.execute("DROP FUNCTION reposhield_checkpoint_immutable()")
