from fastapi import Request


def get_client_ip(request: Request) -> str:
    """
    Identifica o IP mais útil para logs e rate limit quando a API está atrás
    de proxy/reverse proxy, como costuma acontecer em hospedagens.
    """
    for header_name in ("x-forwarded-for", "x-real-ip", "cf-connecting-ip"):
        header_value = request.headers.get(header_name)
        if header_value:
            return header_value.split(",", 1)[0].strip()

    return request.client.host if request.client else "unknown"


def mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "-"

    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked_name = f"{name[:1]}***"
    else:
        masked_name = f"{name[:2]}***{name[-1]}"

    return f"{masked_name}@{domain}"
