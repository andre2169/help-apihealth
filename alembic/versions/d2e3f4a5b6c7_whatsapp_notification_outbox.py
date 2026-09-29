"""WhatsApp notifications and durable delivery outbox.

Revision ID: d2e3f4a5b6c7
Revises: c0d1e2f3a4b5
Create Date: 2026-09-17 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in _inspector().get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in _inspector().get_indexes(table_name))


def _create_index(table_name: str, index_name: str, columns: list[str], unique: bool = False) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index(table_name: str, index_name: str) -> None:
    if _table_exists(table_name) and _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    if _table_exists("users") and not _column_exists("users", "is_active"):
        op.add_column(
            "users",
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )
    _create_index("users", "ix_users_is_active", ["is_active"])

    if _table_exists("notifications") and not _column_exists("notifications", "ticket_event_id"):
        # SQLite não suporta adicionar uma coluna com FK diretamente por
        # ALTER TABLE. O modo batch recria a tabela de forma segura e também
        # funciona normalmente no PostgreSQL.
        with op.batch_alter_table("notifications") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "ticket_event_id",
                    sa.Integer(),
                    sa.ForeignKey(
                        "ticket_events.id",
                        name="fk_notifications_ticket_event_id_ticket_events",
                        ondelete="SET NULL",
                    ),
                    nullable=True,
                )
            )
    _create_index("notifications", "ix_notifications_ticket_event_id", ["ticket_event_id"])

    if not _table_exists("notification_deliveries"):
        op.create_table(
            "notification_deliveries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("notification_id", sa.Integer(), nullable=False),
            sa.Column("recipient_id", sa.Integer(), nullable=False),
            sa.Column("channel", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("processing_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_message_id", sa.String(length=120), nullable=True),
            sa.Column("last_error", sa.String(length=240), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "notification_id",
                "recipient_id",
                "channel",
                name="uq_notification_delivery_recipient_channel",
            ),
        )

    _create_index("notification_deliveries", "ix_notification_deliveries_id", ["id"])
    _create_index(
        "notification_deliveries",
        "ix_notification_deliveries_notification_id",
        ["notification_id"],
    )
    _create_index(
        "notification_deliveries",
        "ix_notification_deliveries_recipient_id",
        ["recipient_id"],
    )
    _create_index("notification_deliveries", "ix_notification_deliveries_channel", ["channel"])
    _create_index("notification_deliveries", "ix_notification_deliveries_status", ["status"])
    _create_index(
        "notification_deliveries",
        "ix_notification_deliveries_next_attempt_at",
        ["next_attempt_at"],
    )
    _create_index(
        "notification_deliveries",
        "ix_notification_deliveries_queued_at",
        ["queued_at"],
    )
    _create_index(
        "notification_deliveries",
        "ix_notification_deliveries_processing_until",
        ["processing_until"],
    )
    _create_index(
        "notification_deliveries",
        "ix_notification_deliveries_status_next_attempt",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    if _table_exists("notification_deliveries"):
        for index_name in (
            "ix_notification_deliveries_status_next_attempt",
            "ix_notification_deliveries_processing_until",
            "ix_notification_deliveries_queued_at",
            "ix_notification_deliveries_next_attempt_at",
            "ix_notification_deliveries_status",
            "ix_notification_deliveries_channel",
            "ix_notification_deliveries_recipient_id",
            "ix_notification_deliveries_notification_id",
            "ix_notification_deliveries_id",
        ):
            _drop_index("notification_deliveries", index_name)
        op.drop_table("notification_deliveries")

    _drop_index("notifications", "ix_notifications_ticket_event_id")
    if _column_exists("notifications", "ticket_event_id"):
        with op.batch_alter_table("notifications") as batch_op:
            batch_op.drop_column("ticket_event_id")

    _drop_index("users", "ix_users_is_active")
    if _column_exists("users", "is_active"):
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("is_active")
