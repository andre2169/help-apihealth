from fastapi import Request
from ipaddress import ip_address

from app.core.config import settings


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None

    candidate = value.strip()
    try:
        return str(ip_address(candidate))
    except ValueError:
        return None


def _trusted_forwarded_ip(request: Request) -> str | None:
    trusted_hops = max(0, settings.TRUSTED_PROXY_HOPS)
    if trusted_hops <= 0:
        return None

    # Estes headers so sao aceitos quando o uso de proxy foi habilitado.
    # Na Shard atual, CF-Connecting-IP contem o IP publico do visitante.
    for header_name in ("cf-connecting-ip", "x-real-ip"):
        header_value = request.headers.get(header_name)
        client_ip = _valid_ip(header_value)
        if client_ip:
            return client_ip

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        hops = [item.strip() for item in forwarded_for.split(",") if item.strip()]
        if hops:
            candidate_index = len(hops) - trusted_hops - 1
            if candidate_index < 0:
                candidate_index = 0
            return _valid_ip(hops[candidate_index])

    return None


def get_client_ip(request: Request) -> str:
    """
    Identifica o IP para logs e rate limit.

    Por padrão usa o IP da conexão TCP. Headers como CF-Connecting-IP,
    X-Real-IP e X-Forwarded-For só são aceitos quando TRUSTED_PROXY_HOPS é
    configurado, evitando spoofing simples.
    """
    forwarded_ip = _trusted_forwarded_ip(request)
    if forwarded_ip:
        return forwarded_ip

    return _valid_ip(request.client.host if request.client else None) or "unknown"


def mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "-"

    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked_name = f"{name[:1]}***"
    else:
        masked_name = f"{name[:2]}***{name[-1]}"

    return f"{masked_name}@{domain}"
