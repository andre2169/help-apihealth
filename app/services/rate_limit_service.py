from datetime import datetime, timedelta

# Armazena tentativas de login em memória.
#
# Estrutura:
#
# {
#     "127.0.0.1:admin@test.com": {
#         "count": 3,
#         "blocked_until": None
#     }
# }
#
failed_logins = {}

# Quantidade máxima de erros permitidos
MAX_ATTEMPTS = 5

# Tempo de bloqueio
BLOCK_TIME_MINUTES = 5


def _build_key(ip: str, email: str) -> str:
    """
    Cria uma chave única.

    Exemplo:
    127.0.0.1:admin@test.com
    """
    return f"{ip}:{email.strip().lower()}"


def check_login_rate_limit(ip: str, email: str) -> bool:
    """
    Verifica se o login está permitido.

    Retorna:
        True  -> pode tentar login
        False -> está bloqueado
    """

    key = _build_key(ip, email)

    login_data = failed_logins.get(key)

    if not login_data:
        return True

    blocked_until = login_data.get("blocked_until")

    # Se não existe bloqueio
    if blocked_until is None:
        return True

    # Se bloqueio já expirou
    if datetime.utcnow() > blocked_until:
        failed_logins.pop(key, None)
        return True

    return False


def register_failed_login(ip: str, email: str):
    """
    Registra uma tentativa de login inválida.
    """

    key = _build_key(ip, email)

    login_data = failed_logins.get(
        key,
        {
            "count": 0,
            "blocked_until": None,
        },
    )

    login_data["count"] += 1

    # Se atingiu limite de erros
    if login_data["count"] >= MAX_ATTEMPTS:

        login_data["blocked_until"] = (
            datetime.utcnow()
            + timedelta(minutes=BLOCK_TIME_MINUTES)
        )

    failed_logins[key] = login_data


def clear_failed_login(ip: str, email: str):
    """
    Remove histórico de falhas após login bem sucedido.
    """

    key = _build_key(ip, email)

    failed_logins.pop(key, None)
