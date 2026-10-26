"""Initial scoped core. Schema is frozen to this revision's DDL snapshot."""

from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    from chattwin.storage.schema_v1 import metadata

    metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup instead")
