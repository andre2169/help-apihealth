"""health context fields

Revision ID: b8c9d0e1f2a3
Revises: 7a1b2c3d4e5f
Create Date: 2026-07-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "7a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sector",
                sa.String(length=80),
                nullable=False,
                server_default="Recepção",
            )
        )
        batch_op.add_column(sa.Column("equipment", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("asset_tag", sa.String(length=80), nullable=True))
        batch_op.add_column(
            sa.Column(
                "operational_impact",
                sa.String(length=20),
                nullable=False,
                server_default="medium",
            )
        )
        batch_op.add_column(
            sa.Column("sla_hours", sa.Integer(), nullable=False, server_default="24")
        )
        batch_op.add_column(sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("due_at")
        batch_op.drop_column("sla_hours")
        batch_op.drop_column("operational_impact")
        batch_op.drop_column("asset_tag")
        batch_op.drop_column("equipment")
        batch_op.drop_column("sector")
