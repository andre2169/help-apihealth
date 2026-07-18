import os
import subprocess
import sys

import uvicorn

from app.main import app
from scripts.seed import create_admin


def run_migrations() -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
    )


if __name__ == "__main__":
    run_migrations()
    create_admin()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
