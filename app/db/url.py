from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_database_url(database_url: str) -> str:
    normalized_url = database_url.strip()

    if normalized_url.startswith("postgres://"):
        normalized_url = normalized_url.replace("postgres://", "postgresql://", 1)

    if normalized_url.startswith("postgresql://"):
        parts = urlsplit(normalized_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        ssl_value = str(query.pop("ssl", "")).lower()

        if ssl_value in {"true", "1", "require"} and not query.get("sslmode"):
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
