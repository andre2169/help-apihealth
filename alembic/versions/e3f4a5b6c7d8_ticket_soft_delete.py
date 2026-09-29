"""add logical deletion fields to tickets

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-09-22 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        if not _column_exists("tickets", "deleted_at"):
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        if not _column_exists("tickets", "deleted_by_id"):
            batch_op.add_column(
                sa.Column(
                    "deleted_by_id",
                    sa.Integer(),
                    sa.ForeignKey(
                        "users.id",
                        name="fk_tickets_deleted_by_id_users",
                        ondelete="SET NULL",
                    ),
                    nullable=True,
                )
            )

    if not _index_exists("tickets", "ix_tickets_deleted_at"):
        op.create_index("ix_tickets_deleted_at", "tickets", ["deleted_at"])
    if not _index_exists("tickets", "ix_tickets_deleted_by_id"):
        op.create_index("ix_tickets_deleted_by_id", "tickets", ["deleted_by_id"])


def downgrade() -> None:
    if _index_exists("tickets", "ix_tickets_deleted_by_id"):
        op.drop_index("ix_tickets_deleted_by_id", table_name="tickets")
    if _index_exists("tickets", "ix_tickets_deleted_at"):
        op.drop_index("ix_tickets_deleted_at", table_name="tickets")

    with op.batch_alter_table("tickets") as batch_op:
        if _column_exists("tickets", "deleted_by_id"):
            batch_op.drop_column("deleted_by_id")
        if _column_exists("tickets", "deleted_at"):
            batch_op.drop_column("deleted_at")
