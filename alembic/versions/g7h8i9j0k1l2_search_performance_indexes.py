"""search and pagination performance indexes

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1, e3f4a5b6c7d8
Create Date: 2026-09-25 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = (
    "f6a7b8c9d0e1",
    "e3f4a5b6c7d8",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    # Prefix search and the administrative tables are the hot paths of the UI.
    _create_index("users", "ix_users_name", ["name"])
    _create_index("tickets", "ix_tickets_deleted_at_id", ["deleted_at", "id"])

    # PostgreSQL needs an expression index to use lower(name) efficiently.
    # SQLite keeps the portable name index above and remains suitable for local
    # development datasets.
    if op.get_bind().dialect.name == "postgresql" and not _index_exists(
        "users", "ix_users_name_lower"
    ):
        op.create_index(
            "ix_users_name_lower",
            "users",
            [sa.text("lower(name)")],
        )


def downgrade() -> None:
    _drop_index("tickets", "ix_tickets_deleted_at_id")
    if op.get_bind().dialect.name == "postgresql":
        _drop_index("users", "ix_users_name_lower")
    _drop_index("users", "ix_users_name")
