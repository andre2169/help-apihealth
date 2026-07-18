"""account verification and profile fields

Revision ID: e5f6a7b8c9d0
Revises: d1e2f3a4b5c6
Create Date: 2026-07-17 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("phone", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("job_title", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("department", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("unit_name", sa.String(length=100), nullable=True))
        batch_op.add_column(
            sa.Column(
                "notification_preference",
                sa.String(length=20),
                nullable=False,
                server_default="email",
            )
        )

    op.create_table(
        "account_verifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("target_value", sa.String(length=255), nullable=True),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_account_verifications_id"), "account_verifications", ["id"], unique=False)
    op.create_index(op.f("ix_account_verifications_purpose"), "account_verifications", ["purpose"], unique=False)
    op.create_index(op.f("ix_account_verifications_target_value"), "account_verifications", ["target_value"], unique=False)
    op.create_index(op.f("ix_account_verifications_user_id"), "account_verifications", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_account_verifications_user_id"), table_name="account_verifications")
    op.drop_index(op.f("ix_account_verifications_target_value"), table_name="account_verifications")
    op.drop_index(op.f("ix_account_verifications_purpose"), table_name="account_verifications")
    op.drop_index(op.f("ix_account_verifications_id"), table_name="account_verifications")
    op.drop_table("account_verifications")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("notification_preference")
        batch_op.drop_column("unit_name")
        batch_op.drop_column("department")
        batch_op.drop_column("job_title")
        batch_op.drop_column("phone")
