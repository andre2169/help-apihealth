from datetime import datetime, timedelta, timezone
import hashlib
import logging
import math
import time
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover - Redis e opcional.
    redis = None

from app.core import security_policy as policy
from app.core.config import settings


logger = logging.getLogger(__name__)

# Fallback local quando Redis nao estiver configurado ou estiver indisponivel.
failed_logins: dict[str, dict[str, Any]] = {}
action_limits: dict[str, dict[str, Any]] = {}

_redis_client: Any | None = None
_redis_unavailable_until = 0.0
_redis_missing_dependency_logged = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_key(value: str) -> str:
    # Email e IP nao precisam ficar legiveis nas chaves temporarias do Redis.
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:32]


def _redis_key(*parts: str) -> str:
    return ":".join(
        [
            policy.REDIS_RATE_LIMIT_PREFIX,
            "auth",
            *(_safe_key(part) for part in parts),
        ]
    )


def _build_redis_client():
    global _redis_client
    global _redis_missing_dependency_logged

    if not settings.REDIS_URL:
        return None

    if redis is None:
        if not _redis_missing_dependency_logged:
            logger.warning(
                "REDIS_URL configurada, mas pacote redis nao esta instalado. "
                "Rate limit de autenticacao distribuido desativado."
            )
            _redis_missing_dependency_logged = True
        return None

    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=policy.REDIS_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=policy.REDIS_OPERATION_TIMEOUT_SECONDS,
        )
    return _redis_client


def _with_redis(operation):
    global _redis_unavailable_until

    now = time.time()
    if not settings.REDIS_URL or now < _redis_unavailable_until:
        return None

    client = _build_redis_client()
    if client is None:
        return None

    try:
        return operation(client)
    except Exception as exc:  # pragma: no cover - depende de servico externo.
        _redis_unavailable_until = now + policy.REDIS_FALLBACK_SECONDS
        logger.warning(
            "Redis indisponivel para rate limit de autenticacao; usando memoria local por %ss | error=%s",
            policy.REDIS_FALLBACK_SECONDS,
            exc.__class__.__name__,
        )
        return None


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _build_ip_key(ip: str, email: str) -> str:
    # O contexto combina IP e email normalizado. Assim, um erro de uma conta
    # nao bloqueia todas as pessoas que compartilham a mesma rede publica.
    return f"ip:{ip}:{_normalize_email(email)}"


def _build_account_key(email: str) -> str:
    return f"account:{_normalize_email(email)}"


def _login_block_seconds(failure_count: int) -> int:
    level = max(0, failure_count // policy.LOGIN_FAILURE_THRESHOLD - 1)
    return policy.LOGIN_LOCK_DURATIONS_SECONDS[
        min(level, len(policy.LOGIN_LOCK_DURATIONS_SECONDS) - 1)
    ]


def _keys_for(ip: str, email: str, *, include_account: bool = True) -> tuple[str, ...]:
    keys = [_build_ip_key(ip, email)]
    if include_account:
        keys.append(_build_account_key(email))
    return tuple(keys)


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
    if len(failed_logins) < policy.MAX_TRACKED_RATE_LIMIT_KEYS:
        return

    retention = timedelta(seconds=policy.LOGIN_FAILURE_WINDOW_SECONDS)
    expired_keys = []
    for key, login_data in failed_logins.items():
        last_attempt_at = login_data.get("last_attempt_at") or now
        if now - last_attempt_at > retention:
            expired_keys.append(key)

    for key in expired_keys:
        failed_logins.pop(key, None)


def _store_bounded(
    bucket: dict[str, dict[str, Any]],
    key: str,
    value: dict[str, Any],
) -> None:
    bucket.pop(key, None)
    bucket[key] = value
    while len(bucket) > policy.MAX_TRACKED_RATE_LIMIT_KEYS:
        bucket.pop(next(iter(bucket)))


def check_login_rate_limit(ip: str, email: str, *, include_account: bool = True) -> bool:
    """
    Verifica se o login está permitido.

    O bloqueio e checado antes do bcrypt para poupar recursos e permanece
    efetivo durante toda a janela, inclusive quando a senha informada estiver
    correta. O desbloqueio ocorre somente pelo fim do prazo ou pela limpeza
    apos um login permitido.

    Retorna:
        True  -> pode tentar login
        False -> está bloqueado
    """

    redis_result = _check_login_rate_limit_redis(
        ip,
        email,
        include_account=include_account,
    )
    if redis_result is not None:
        return redis_result

    now = _utc_now()
    _cleanup_failed_logins(now)

    for key in _keys_for(ip, email, include_account=include_account):
        login_data = failed_logins.get(key)
        if _is_blocked(login_data, now):
            return False
    return True


def get_login_retry_after(ip: str, email: str) -> int:
    """Returns the remaining login block in seconds, rounded up."""
    redis_result = _get_login_retry_after_redis(ip, email)
    if redis_result is not None:
        return max(0, int(redis_result))

    now = _utc_now()
    remaining = 0.0
    for key in _keys_for(ip, email, include_account=True):
        login_data = failed_logins.get(key)
        blocked_until = login_data.get("blocked_until") if login_data else None
        if blocked_until:
            remaining = max(remaining, (blocked_until - now).total_seconds())

    return max(0, math.ceil(remaining))


def register_failed_login(ip: str, email: str):
    """
    Registra uma tentativa de login inválida.
    """
    if _register_failed_login_redis(ip, email):
        return

    now = _utc_now()
    _cleanup_failed_logins(now)

    for key in _keys_for(ip, email, include_account=True):
        login_data = failed_logins.get(
            key,
            {
                "count": 0,
                "blocked_until": None,
                "last_attempt_at": now,
            },
        )

        if now - login_data["last_attempt_at"] > timedelta(
            seconds=policy.LOGIN_FAILURE_WINDOW_SECONDS
        ):
            login_data = {
                "count": 0,
                "blocked_until": None,
                "last_attempt_at": now,
            }

        login_data["count"] += 1
        login_data["last_attempt_at"] = now

        # A cada cinco falhas avanca uma faixa da tabela progressiva.
        if login_data["count"] % policy.LOGIN_FAILURE_THRESHOLD == 0:
            login_data["blocked_until"] = now + timedelta(
                seconds=_login_block_seconds(login_data["count"])
            )

        _store_bounded(failed_logins, key, login_data)


def clear_failed_login(ip: str, email: str):
    """
    Remove histórico de falhas após login bem sucedido.
    """
    _clear_failed_login_redis(ip, email)

    for key in _keys_for(ip, email, include_account=True):
        failed_logins.pop(key, None)


def _check_login_rate_limit_redis(
    ip: str,
    email: str,
    *,
    include_account: bool = False,
) -> bool | None:
    def operation(client):
        for key in _keys_for(ip, email, include_account=include_account):
            if client.exists(_redis_key("login", "block", key)):
                return False
        return True

    return _with_redis(operation)


def _register_failed_login_redis(ip: str, email: str) -> bool:
    window_seconds = policy.LOGIN_FAILURE_WINDOW_SECONDS

    def operation(client):
        pipe = client.pipeline()
        keys = list(_keys_for(ip, email, include_account=True))
        count_keys = [_redis_key("login", "fail", key) for key in keys]
        block_keys = [_redis_key("login", "block", key) for key in keys]

        for count_key in count_keys:
            pipe.incr(count_key)
            pipe.expire(count_key, window_seconds)
        counts = pipe.execute()[0::2]

        pipe = client.pipeline()
        for count, block_key in zip(counts, block_keys):
            count = int(count)
            if count % policy.LOGIN_FAILURE_THRESHOLD == 0:
                pipe.set(block_key, "1", ex=_login_block_seconds(count))
        pipe.execute()
        return True

    return bool(_with_redis(operation))


def _clear_failed_login_redis(ip: str, email: str) -> None:
    def operation(client):
        keys = []
        for key in _keys_for(ip, email, include_account=True):
            keys.append(_redis_key("login", "fail", key))
            keys.append(_redis_key("login", "block", key))
        if keys:
            client.delete(*keys)
        return True

    _with_redis(operation)


def _get_login_retry_after_redis(ip: str, email: str) -> int | None:
    def operation(client):
        ttls = []
        for key in _keys_for(ip, email, include_account=True):
            ttl = int(client.ttl(_redis_key("login", "block", key)))
            if ttl > 0:
                ttls.append(ttl)
        return max(ttls, default=0)

    return _with_redis(operation)


def consume_action_rate_limit(
    *,
    action: str,
    key: str,
    max_requests: int,
    window_seconds: int,
) -> bool:
    """
    Rate limit leve para fluxos sensiveis sem gravar no SQLite a cada request.

    Retorna True quando a acao pode seguir. Retorna False quando a chave
    excedeu o limite da janela atual.
    """
    redis_result = _consume_action_rate_limit_redis(
        action=action,
        key=key,
        max_requests=max_requests,
        window_seconds=window_seconds,
    )
    if redis_result is not None:
        return redis_result

    now = _utc_now()
    normalized_key = f"{action}:{key.strip().lower()}"
    window = timedelta(seconds=window_seconds)

    if len(action_limits) >= policy.MAX_TRACKED_RATE_LIMIT_KEYS:
        expired_keys = [
            bucket_key
            for bucket_key, data in action_limits.items()
            if now - data.get("window_start", now) > window
        ]
        for bucket_key in expired_keys:
            action_limits.pop(bucket_key, None)

    data = action_limits.get(
        normalized_key,
        {
            "count": 0,
            "window_start": now,
        },
    )

    if now - data["window_start"] > window:
        data = {
            "count": 0,
            "window_start": now,
        }

    data["count"] += 1
    _store_bounded(action_limits, normalized_key, data)

    return data["count"] <= max_requests


def _consume_action_rate_limit_redis(
    *,
    action: str,
    key: str,
    max_requests: int,
    window_seconds: int,
) -> bool | None:
    normalized_key = f"{action}:{key.strip().lower()}"
    now = time.time()
    bucket_id = int(now // window_seconds)

    def operation(client):
        redis_key = _redis_key("action", normalized_key, str(bucket_id))
        count = int(client.incr(redis_key))
        if count == 1:
            client.expire(redis_key, window_seconds + 5)
        return count <= max_requests

    return _with_redis(operation)
