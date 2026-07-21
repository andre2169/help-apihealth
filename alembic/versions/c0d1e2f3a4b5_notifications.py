"""notifications

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-07-20 23:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _create_index(table_name: str, index_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _drop_index(table_name: str, index_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    if not _table_exists("notifications"):
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("recipient_id", sa.Integer(), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column("ticket_id", sa.Integer(), nullable=True),
            sa.Column("type", sa.String(length=80), nullable=False),
            sa.Column("title", sa.String(length=140), nullable=False),
            sa.Column("message", sa.String(length=280), nullable=False),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    _create_index("notifications", "ix_notifications_id", ["id"])
    _create_index("notifications", "ix_notifications_recipient_id", ["recipient_id"])
    _create_index("notifications", "ix_notifications_actor_id", ["actor_id"])
    _create_index("notifications", "ix_notifications_ticket_id", ["ticket_id"])
    _create_index("notifications", "ix_notifications_type", ["type"])
    _create_index("notifications", "ix_notifications_is_read", ["is_read"])
    _create_index("notifications", "ix_notifications_created_at", ["created_at"])
    _create_index(
        "notifications",
        "ix_notifications_recipient_read_created",
        ["recipient_id", "is_read", "created_at"],
    )


def downgrade() -> None:
    if _table_exists("notifications"):
        _drop_index("notifications", "ix_notifications_recipient_read_created")
        _drop_index("notifications", "ix_notifications_created_at")
        _drop_index("notifications", "ix_notifications_is_read")
        _drop_index("notifications", "ix_notifications_type")
        _drop_index("notifications", "ix_notifications_ticket_id")
        _drop_index("notifications", "ix_notifications_actor_id")
        _drop_index("notifications", "ix_notifications_recipient_id")
        _drop_index("notifications", "ix_notifications_id")
        op.drop_table("notifications")
