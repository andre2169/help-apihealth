"""ticket priority and category

Revision ID: 7a1b2c3d4e5f
Revises: e3a51afa587d
Create Date: 2026-07-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "e3a51afa587d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "category",
                sa.String(length=60),
                nullable=False,
                server_default="Geral",
            )
        )
        batch_op.add_column(
            sa.Column(
                "priority",
                sa.String(length=20),
                nullable=False,
                server_default="medium",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_column("priority")
        batch_op.drop_column("category")
