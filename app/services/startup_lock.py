import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from app.core.config import settings


def _sqlite_database_path() -> Path | None:
    database_url = settings.DATABASE_URL.strip()
    if not database_url.startswith("sqlite:///"):
        return None

    raw_path = database_url.removeprefix("sqlite:///").split("?", 1)[0]
    if not raw_path or raw_path == ":memory:":
        return None

    return Path(raw_path).expanduser().resolve()


def _default_lock_path() -> Path:
    if settings.STARTUP_LOCK_PATH:
        return Path(settings.STARTUP_LOCK_PATH).expanduser().resolve()

    sqlite_path = _sqlite_database_path()
    if sqlite_path:
        return sqlite_path.with_name(f"{sqlite_path.name}.startup.lock")

    return Path(tempfile.gettempdir(), "helphealth-api.startup.lock")


def _is_stale_lock(lock_path: Path, now: float) -> bool:
    try:
        age = now - lock_path.stat().st_mtime
    except FileNotFoundError:
        return False

    return age > settings.STARTUP_LOCK_STALE_SECONDS


def _acquire_lock(lock_path: Path) -> int:
    deadline = time.monotonic() + settings.STARTUP_LOCK_TIMEOUT_SECONDS
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            os.write(descriptor, f"{os.getpid()}\n".encode("utf-8"))
            return descriptor
        except FileExistsError:
            now = time.time()
            if _is_stale_lock(lock_path, now):
                try:
                    lock_path.unlink()
                    continue
                except FileNotFoundError:
                    continue

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Timeout aguardando lock de inicializacao: {lock_path}"
                )

            time.sleep(1)


@contextmanager
def startup_lock():
    """
    Evita corrida entre migracoes/admin inicial quando a hospedagem inicia mais
    de um processo ao mesmo tempo usando o mesmo arquivo SQLite.
    """
    lock_path = _default_lock_path()
    descriptor = _acquire_lock(lock_path)
    try:
        yield lock_path
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
