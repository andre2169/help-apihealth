import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_notice_migration_preserves_existing_data_and_enforces_receipt_keys(tmp_path):
    file = Path(__file__).resolve().parents[1] / "alembic/versions/j0k1l2m3n4o5_persistent_notice_reads.py"
    spec = importlib.util.spec_from_file_location("notice_reads_migration", file)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///" + (tmp_path / "migration.db").as_posix())
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.Integer, primary_key=True))
    notices = sa.Table("maintenance_notices", metadata, sa.Column("id", sa.Integer, primary_key=True),
                       sa.Column("title", sa.String(100), nullable=False), sa.Column("message", sa.Text, nullable=False))
    metadata.create_all(engine)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            with connection.begin():
                connection.execute(sa.insert(users).values(id=1))
                connection.execute(sa.insert(notices).values(id=1, title="Aviso existente", message="Conteúdo preservado"))
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    migration.upgrade()
                    reflected = sa.Table("maintenance_notices", sa.MetaData(), autoload_with=connection)
                    row = connection.execute(sa.select(reflected)).mappings().one()
                    assert row["title"] == "Aviso existente"
                    assert row["message"] == "Conteúdo preservado"
                    assert row["audience"] == "all"
                    assert row["revision"] == 1
                    receipts = sa.Table("maintenance_notice_reads", sa.MetaData(), autoload_with=connection)
                    assert {column.name for column in receipts.primary_key} == {"notice_id", "user_id"}
                    connection.execute(sa.insert(receipts).values(user_id=1, notice_id=1, revision=1))
                    assert connection.scalar(sa.select(sa.func.count()).select_from(receipts)) == 1
                    migration.downgrade()
                    assert "maintenance_notice_reads" not in sa.inspect(connection).get_table_names()
                    migration.upgrade()
                    assert connection.scalar(sa.select(sa.func.count()).select_from(notices)) == 1
                    receipts = sa.Table("maintenance_notice_reads", sa.MetaData(), autoload_with=connection)
                    connection.execute(sa.insert(receipts).values(user_id=1, notice_id=1, revision=1))
                    connection.execute(sa.delete(users).where(users.c.id == 1))
                    assert connection.scalar(sa.select(sa.func.count()).select_from(receipts)) == 0
    finally:
        engine.dispose()
