import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

# --------------------------------------------------
# Permite o Alembic enxergar o pacote "app"
# --------------------------------------------------
sys.path.append(str(Path(__file__).resolve().parents[1]))

# --------------------------------------------------
# Imports da aplicação
# --------------------------------------------------
from app.db.session import engine
from app.db.base import Base

# --------------------------------------------------
# Configuração básica do Alembic
# --------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata dos models (users, tickets, comments)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Modo offline:
    - Gera SQL sem conectar no banco
    - Pouco usado no dia a dia
    """
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Modo online:
    - Conecta no banco de verdade
    - Executa as migrations
    """
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # detecta mudança de tipo de coluna
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
