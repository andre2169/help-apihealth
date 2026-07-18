from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql://", 1)
    return database_url


database_url = normalize_database_url(settings.DATABASE_URL)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}

engine = create_engine(
    database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)
