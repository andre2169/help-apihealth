from datetime import datetime, timedelta
from typing import Any

# Armazena tentativas de login em memória.
#
# Estrutura:
#
# {
#     "ip:127.0.0.1:admin@test.com": {
#         "count": 3,
#         "blocked_until": None,
#         "last_attempt_at": datetime(...)
#     }
# }
#
failed_logins: dict[str, dict[str, Any]] = {}

# Quantidade máxima de erros permitidos
MAX_ATTEMPTS = 5

# Tempo de bloqueio
BLOCK_TIME_MINUTES = 5

# Limite defensivo para impedir crescimento indefinido em memória.
MAX_TRACKED_KEYS = 5000


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _build_ip_key(ip: str, email: str) -> str:
    return f"ip:{ip}:{_normalize_email(email)}"


def _build_account_key(email: str) -> str:
    return f"account:{_normalize_email(email)}"


def _keys_for(ip: str, email: str) -> tuple[str, str]:
    return _build_ip_key(ip, email), _build_account_key(email)


def _is_blocked(login_data: dict[str, Any] | None, now: datetime) -> bool:
    if not login_data:
        return False

    blocked_until = login_data.get("blocked_until")
    if blocked_until is None:
        return False

    if now > blocked_until:
        return False

    return True


def _cleanup_failed_logins(now: datetime) -> None:
    if len(failed_logins) < MAX_TRACKED_KEYS:
        return

    retention = timedelta(minutes=BLOCK_TIME_MINUTES * 2)
    expired_keys = []
    for key, login_data in failed_logins.items():
        blocked_until = login_data.get("blocked_until")
        last_attempt_at = login_data.get("last_attempt_at") or now
        if blocked_until and now > blocked_until:
            expired_keys.append(key)
        elif not blocked_until and now - last_attempt_at > retention:
            expired_keys.append(key)

    for key in expired_keys:
        failed_logins.pop(key, None)


def check_login_rate_limit(ip: str, email: str) -> bool:
    """
    Verifica se o login está permitido.

    Retorna:
        True  -> pode tentar login
        False -> está bloqueado
    """

    now = datetime.utcnow()
    _cleanup_failed_logins(now)

    for key in _keys_for(ip, email):
        login_data = failed_logins.get(key)
        if _is_blocked(login_data, now):
            return False
        if login_data and login_data.get("blocked_until") and now > login_data["blocked_until"]:
            failed_logins.pop(key, None)

    return True


def register_failed_login(ip: str, email: str):
    """
    Registra uma tentativa de login inválida.
    """
    now = datetime.utcnow()
    _cleanup_failed_logins(now)

    for key in _keys_for(ip, email):
        login_data = failed_logins.get(
            key,
            {
                "count": 0,
                "blocked_until": None,
                "last_attempt_at": now,
            },
        )

        login_data["count"] += 1
        login_data["last_attempt_at"] = now

        # Se atingiu limite de erros
        if login_data["count"] >= MAX_ATTEMPTS:
            login_data["blocked_until"] = now + timedelta(minutes=BLOCK_TIME_MINUTES)

        failed_logins[key] = login_data


def clear_failed_login(ip: str, email: str):
    """
    Remove histórico de falhas após login bem sucedido.
    """
    for key in _keys_for(ip, email):
        failed_logins.pop(key, None)
