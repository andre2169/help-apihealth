import logging
import json
import sys
from datetime import datetime, timezone

from app.core import security_policy as policy


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class ReadableTextFormatter(logging.Formatter):
    """Mantem o formato simples e separa eventos da aplicacao no terminal."""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if record.name.startswith(("app.", "alembic.")):
            return f"{formatted}\n"
        return formatted


def setup_logging():
    log_level = getattr(logging, policy.LOG_LEVEL.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)

    if policy.LOG_FORMAT.lower() == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            ReadableTextFormatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
            )
        )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)
    root_logger.addHandler(handler)

    # O middleware da aplicacao ja registra rota, status e request_id. O
    # access logger do Uvicorn repetia cada requisicao sem esse contexto.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.setLevel(logging.WARNING)

    logging.basicConfig(
        level=log_level,
        handlers=[handler],
    )
