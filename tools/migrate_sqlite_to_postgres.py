"""
Migra dados do SQLite local para um PostgreSQL ja migrado com Alembic.

Uso:
  python tools/migrate_sqlite_to_postgres.py --sqlite sqlite:///./helphealth.db --postgres postgresql://...

Se a hospedagem fornecer URL com "postgres://" ou "?ssl=true", o script
normaliza para o formato aceito pelo SQLAlchemy/psycopg2.

Por seguranca, o script recusa copiar para tabelas com dados. Use --replace
apenas se voce tiver certeza de que pode limpar o banco PostgreSQL de destino.
"""
from __future__ import annotations

import argparse
import os
from typing import Iterable

from dotenv import load_dotenv
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.engine import Engine

from app.db.base import Base
from app.db.url import normalize_database_url


def _engine(database_url: str) -> Engine:
    normalized_url = normalize_database_url(database_url)
    connect_args = {"check_same_thread": False} if normalized_url.startswith("sqlite") else {}
    return create_engine(normalized_url, pool_pre_ping=True, connect_args=connect_args)


def _tables_in_order() -> list:
    return list(Base.metadata.sorted_tables)


def _table_count(engine: Engine, table) -> int:
    with engine.connect() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def _ensure_destination_empty(postgres_engine: Engine, tables: Iterable) -> None:
    occupied = [
        table.name
        for table in tables
        if _table_count(postgres_engine, table) > 0
    ]
    if occupied:
        names = ", ".join(occupied)
        raise SystemExit(
            f"O PostgreSQL de destino ja tem dados em: {names}. "
            "Use --replace somente se puder limpar esses dados antes da copia."
        )


def _clear_destination(postgres_engine: Engine, tables: Iterable) -> None:
    with postgres_engine.begin() as connection:
        for table in reversed(list(tables)):
            connection.execute(table.delete())


def _copy_table(source_engine: Engine, target_engine: Engine, table) -> int:
    with source_engine.connect() as source_connection:
        rows = [dict(row) for row in source_connection.execute(select(table)).mappings()]

    if not rows:
        return 0

    with target_engine.begin() as target_connection:
        target_connection.execute(insert(table), rows)

    return len(rows)


def _reset_postgres_sequences(postgres_engine: Engine, tables: Iterable) -> None:
    if postgres_engine.dialect.name != "postgresql":
        return

    with postgres_engine.begin() as connection:
        for table in tables:
            integer_pk = None
            for column in table.primary_key.columns:
                try:
                    if column.type.python_type is int:
                        integer_pk = column
                        break
                except NotImplementedError:
                    continue
            if integer_pk is None:
                continue

            sequence_name = connection.execute(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": integer_pk.name},
            ).scalar()
            if not sequence_name:
                continue

            max_id = connection.execute(select(func.max(integer_pk))).scalar()
            if max_id:
                connection.execute(
                    text("SELECT setval(:sequence_name, :next_id, true)"),
                    {"sequence_name": sequence_name, "next_id": int(max_id)},
                )


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Migra dados do SQLite para PostgreSQL.")
    parser.add_argument("--sqlite", default=os.getenv("SQLITE_DATABASE_URL"))
    parser.add_argument("--postgres", default=os.getenv("POSTGRES_DATABASE_URL"))
    parser.add_argument("--replace", action="store_true", help="Limpa o PostgreSQL antes de copiar.")
    args = parser.parse_args()

    if not args.sqlite or not args.postgres:
        raise SystemExit("Informe --sqlite e --postgres ou use SQLITE_DATABASE_URL/POSTGRES_DATABASE_URL.")

    sqlite_engine = _engine(args.sqlite)
    postgres_engine = _engine(args.postgres)
    tables = _tables_in_order()

    if args.replace:
        _clear_destination(postgres_engine, tables)
    else:
        _ensure_destination_empty(postgres_engine, tables)

    total = 0
    for table in tables:
        copied = _copy_table(sqlite_engine, postgres_engine, table)
        total += copied
        print(f"{table.name}: {copied} registro(s) copiado(s)")

    _reset_postgres_sequences(postgres_engine, tables)
    print(f"Concluido. Total copiado: {total} registro(s).")


if __name__ == "__main__":
    main()
