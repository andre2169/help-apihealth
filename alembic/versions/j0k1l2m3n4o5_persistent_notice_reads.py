"""Track notice audiences and the version read by each user."""

from alembic import op
import sqlalchemy as sa


revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("maintenance_notices", sa.Column("audience", sa.String(20), nullable=False, server_default="all"))
    op.add_column("maintenance_notices", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "maintenance_notice_reads",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("notice_id", sa.Integer(), sa.ForeignKey("maintenance_notices.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_maintenance_notice_reads_notice_id", "maintenance_notice_reads", ["notice_id"])


def downgrade():
    op.drop_index("ix_maintenance_notice_reads_notice_id", table_name="maintenance_notice_reads")
    op.drop_table("maintenance_notice_reads")
    with op.batch_alter_table("maintenance_notices") as batch:
        batch.drop_column("revision")
        batch.drop_column("audience")
