"""Immutable model endpoint versions, explicitly selected by scoped sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table(
        "model_deployments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("persona_id", sa.String(), sa.ForeignKey("personas.id"), nullable=False),
        sa.Column(
            "relationship_id", sa.String(), sa.ForeignKey("relationships.id"), nullable=False
        ),
        sa.Column("artifact_id", sa.String(), sa.ForeignKey("model_artifacts.id")),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_model_deployments_scope", "model_deployments", ["persona_id", "relationship_id"]
    )


def downgrade():
    raise RuntimeError("Restore a verified backup; destructive downgrade is disabled")
