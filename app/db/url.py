from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


LOCAL_DATABASE_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


def normalize_database_url(database_url: str) -> str:
    normalized_url = database_url.strip()

    if normalized_url.startswith("postgres://"):
        normalized_url = normalized_url.replace("postgres://", "postgresql://", 1)

    if normalized_url.startswith("postgresql://"):
        parts = urlsplit(normalized_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        ssl_value = str(query.pop("ssl", "")).lower()
        host = (parts.hostname or "").lower()
        is_local_host = host in LOCAL_DATABASE_HOSTS

        sslmode = str(query.get("sslmode", "")).lower()
        secure_ssl_modes = {"require", "verify-ca", "verify-full"}
        if not is_local_host and sslmode not in secure_ssl_modes:
            # Uma URL remota nunca deve conseguir desativar TLS por engano.
            query["sslmode"] = "require"
        elif not sslmode and ssl_value in {"true", "1", "require"}:
            query["sslmode"] = "require"

        normalized_url = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(query),
                parts.fragment,
            )
        )

    return normalized_url
