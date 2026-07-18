"""ticket multiple issue images

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-18 10:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _column_exists("tickets", "issue_images"):
        with op.batch_alter_table("tickets") as batch_op:
            batch_op.add_column(sa.Column("issue_images", sa.JSON(), nullable=True))


def downgrade() -> None:
    if _column_exists("tickets", "issue_images"):
        with op.batch_alter_table("tickets") as batch_op:
            batch_op.drop_column("issue_images")
