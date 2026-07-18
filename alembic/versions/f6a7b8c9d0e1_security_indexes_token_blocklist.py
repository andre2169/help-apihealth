"""security indexes and token blocklist

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-17 14:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _create_index(table_name: str, index_name: str, columns: list[str], unique: bool = False) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index(table_name: str, index_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    op.create_table(
        "token_blocklist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("token_blocklist", "ix_token_blocklist_id", ["id"])
    _create_index("token_blocklist", "ix_token_blocklist_jti", ["jti"], unique=True)
    _create_index("token_blocklist", "ix_token_blocklist_user_id", ["user_id"])
    _create_index("token_blocklist", "ix_token_blocklist_expires_at", ["expires_at"])

    _create_index("users", "ix_users_role", ["role"])
    _create_index("users", "ix_users_created_at", ["created_at"])

    _create_index("tickets", "ix_tickets_status", ["status"])
    _create_index("tickets", "ix_tickets_user_id", ["user_id"])
    _create_index("tickets", "ix_tickets_technician_id", ["technician_id"])
    _create_index("tickets", "ix_tickets_created_at", ["created_at"])
    _create_index("tickets", "ix_tickets_due_at", ["due_at"])
    _create_index("tickets", "ix_tickets_resolved_at", ["resolved_at"])
    _create_index("tickets", "ix_tickets_priority", ["priority"])
    _create_index("tickets", "ix_tickets_category", ["category"])
    _create_index("tickets", "ix_tickets_sector", ["sector"])
    _create_index("tickets", "ix_tickets_equipment", ["equipment"])
    _create_index("tickets", "ix_tickets_operational_impact", ["operational_impact"])
    _create_index("tickets", "ix_tickets_status_created_at", ["status", "created_at"])
    _create_index("tickets", "ix_tickets_user_created_at", ["user_id", "created_at"])
    _create_index("tickets", "ix_tickets_technician_status", ["technician_id", "status"])

    _create_index("comments", "ix_comments_user_id", ["user_id"])
    _create_index("comments", "ix_comments_ticket_id", ["ticket_id"])
    _create_index("comments", "ix_comments_created_at", ["created_at"])
    _create_index("comments", "ix_comments_ticket_created_at", ["ticket_id", "created_at"])

    _create_index("ticket_events", "ix_ticket_events_ticket_id", ["ticket_id"])
    _create_index("ticket_events", "ix_ticket_events_user_id", ["user_id"])
    _create_index("ticket_events", "ix_ticket_events_event_type", ["event_type"])
    _create_index("ticket_events", "ix_ticket_events_created_at", ["created_at"])
    _create_index("ticket_events", "ix_ticket_events_ticket_created_at", ["ticket_id", "created_at"])
    _create_index("ticket_events", "ix_ticket_events_ticket_type", ["ticket_id", "event_type"])

    _create_index(
        "account_verifications",
        "ix_account_verifications_user_purpose_target_used",
        ["user_id", "purpose", "target_value", "used_at"],
    )


def downgrade() -> None:
    _drop_index("account_verifications", "ix_account_verifications_user_purpose_target_used")

    _drop_index("ticket_events", "ix_ticket_events_ticket_type")
    _drop_index("ticket_events", "ix_ticket_events_ticket_created_at")
    _drop_index("ticket_events", "ix_ticket_events_created_at")
    _drop_index("ticket_events", "ix_ticket_events_event_type")
    _drop_index("ticket_events", "ix_ticket_events_user_id")
    _drop_index("ticket_events", "ix_ticket_events_ticket_id")

    _drop_index("comments", "ix_comments_ticket_created_at")
    _drop_index("comments", "ix_comments_created_at")
    _drop_index("comments", "ix_comments_ticket_id")
    _drop_index("comments", "ix_comments_user_id")

    _drop_index("tickets", "ix_tickets_technician_status")
    _drop_index("tickets", "ix_tickets_user_created_at")
    _drop_index("tickets", "ix_tickets_status_created_at")
    _drop_index("tickets", "ix_tickets_operational_impact")
    _drop_index("tickets", "ix_tickets_equipment")
    _drop_index("tickets", "ix_tickets_sector")
    _drop_index("tickets", "ix_tickets_category")
    _drop_index("tickets", "ix_tickets_priority")
    _drop_index("tickets", "ix_tickets_resolved_at")
    _drop_index("tickets", "ix_tickets_due_at")
    _drop_index("tickets", "ix_tickets_created_at")
    _drop_index("tickets", "ix_tickets_technician_id")
    _drop_index("tickets", "ix_tickets_user_id")
    _drop_index("tickets", "ix_tickets_status")

    _drop_index("users", "ix_users_created_at")
    _drop_index("users", "ix_users_role")

    _drop_index("token_blocklist", "ix_token_blocklist_expires_at")
    _drop_index("token_blocklist", "ix_token_blocklist_user_id")
    _drop_index("token_blocklist", "ix_token_blocklist_jti")
    _drop_index("token_blocklist", "ix_token_blocklist_id")
    op.drop_table("token_blocklist")
