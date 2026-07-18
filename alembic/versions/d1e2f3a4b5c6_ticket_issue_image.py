"""ticket issue image

Revision ID: d1e2f3a4b5c6
Revises: c4d5e6f7a8b9
Create Date: 2026-07-14 21:45:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("issue_image", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_column("issue_image")
