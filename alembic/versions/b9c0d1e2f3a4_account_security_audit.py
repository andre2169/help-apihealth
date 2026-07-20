"""account security and audit trail

Revision ID: b9c0d1e2f3a4
Revises: a7b8c9d0e1f2
Create Date: 2026-07-20 15:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


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
    with op.batch_alter_table("users") as batch_op:
        if not _column_exists("users", "session_version"):
            batch_op.add_column(
                sa.Column("session_version", sa.Integer(), nullable=False, server_default="1")
            )
        if not _column_exists("users", "email_verified"):
            batch_op.add_column(
                sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if not _column_exists("users", "email_verified_at"):
            batch_op.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        "UPDATE users "
        "SET session_version = COALESCE(session_version, 1), "
        "email_verified = TRUE, "
        "email_verified_at = COALESCE(email_verified_at, CURRENT_TIMESTAMP)"
    )
    _create_index("users", "ix_users_email_verified", ["email_verified"])

    if not _table_exists("audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(length=80), nullable=False),
            sa.Column("target_type", sa.String(length=60), nullable=False),
            sa.Column("target_id", sa.Integer(), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)")),
            sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    _create_index("audit_events", "ix_audit_events_id", ["id"])
    _create_index("audit_events", "ix_audit_events_actor_id", ["actor_id"])
    _create_index("audit_events", "ix_audit_events_action", ["action"])
    _create_index("audit_events", "ix_audit_events_target_type", ["target_type"])
    _create_index("audit_events", "ix_audit_events_target_id", ["target_id"])
    _create_index("audit_events", "ix_audit_events_created_at", ["created_at"])


def downgrade() -> None:
    if _table_exists("audit_events"):
        _drop_index("audit_events", "ix_audit_events_created_at")
        _drop_index("audit_events", "ix_audit_events_target_id")
        _drop_index("audit_events", "ix_audit_events_target_type")
        _drop_index("audit_events", "ix_audit_events_action")
        _drop_index("audit_events", "ix_audit_events_actor_id")
        _drop_index("audit_events", "ix_audit_events_id")
        op.drop_table("audit_events")

    _drop_index("users", "ix_users_email_verified")

    with op.batch_alter_table("users") as batch_op:
        if _column_exists("users", "email_verified_at"):
            batch_op.drop_column("email_verified_at")
        if _column_exists("users", "email_verified"):
            batch_op.drop_column("email_verified")
        if _column_exists("users", "session_version"):
            batch_op.drop_column("session_version")
