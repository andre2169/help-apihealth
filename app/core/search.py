"""Helpers compartilhados para buscas textuais seguras e previsíveis."""


LIKE_ESCAPE = "\\"
MAX_SEARCH_LENGTH = 80


def normalize_search(value: str | None, *, max_length: int = MAX_SEARCH_LENGTH) -> str:
    """Normaliza espacos e limita o texto antes de montar uma consulta."""
    if not value:
        return ""
    return " ".join(str(value).strip().split())[:max_length]


def escape_like(value: str) -> str:
    """Escapa curingas para o usuario nao transformar a busca em wildcard."""
    return (
        value.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", f"{LIKE_ESCAPE}%")
        .replace("_", f"{LIKE_ESCAPE}_")
    )


def prefix_pattern(value: str) -> str:
    return f"{escape_like(value)}%"


def contains_pattern(value: str) -> str:
    return f"%{escape_like(value)}%"


def page_rows(query, *, skip: int, limit: int):
    """Busca uma pagina mais um item, evitando um COUNT separado."""
    rows = query.offset(max(skip, 0)).limit(max(limit, 1) + 1).all()
    has_more = len(rows) > limit
    return rows[:limit], has_more
