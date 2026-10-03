"""Add MFA recovery codes and operational notices."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, Sequence[str], None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])
    op.create_index("ix_mfa_recovery_codes_used_at", "mfa_recovery_codes", ["used_at"])
    op.create_index(
        "ix_mfa_recovery_codes_user_unused",
        "mfa_recovery_codes",
        ["user_id", "used_at"],
    )

    op.create_table(
        "maintenance_notices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column(
            "target_sectors",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_maintenance_notices_starts_at", "maintenance_notices", ["starts_at"])
    op.create_index("ix_maintenance_notices_ends_at", "maintenance_notices", ["ends_at"])
    op.create_index("ix_maintenance_notices_active", "maintenance_notices", ["active"])
    op.create_index(
        "ix_maintenance_notices_active_window",
        "maintenance_notices",
        ["active", "starts_at", "ends_at"],
    )
    op.create_index(
        "ix_maintenance_notices_created_by_id",
        "maintenance_notices",
        ["created_by_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_maintenance_notices_created_by_id", table_name="maintenance_notices")
    op.drop_index("ix_maintenance_notices_active_window", table_name="maintenance_notices")
    op.drop_index("ix_maintenance_notices_active", table_name="maintenance_notices")
    op.drop_index("ix_maintenance_notices_ends_at", table_name="maintenance_notices")
    op.drop_index("ix_maintenance_notices_starts_at", table_name="maintenance_notices")
    op.drop_table("maintenance_notices")

    op.drop_index("ix_mfa_recovery_codes_user_unused", table_name="mfa_recovery_codes")
    op.drop_index("ix_mfa_recovery_codes_used_at", table_name="mfa_recovery_codes")
    op.drop_index("ix_mfa_recovery_codes_user_id", table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
