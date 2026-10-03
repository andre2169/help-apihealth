from app.core.config import settings
from app.db.models.notification import Notification
from app.schemas.validators import validate_optional_phone

LEVEL_LABELS = {
    "low": "Baixa",
    "medium": "Média",
    "high": "Alta",
    "critical": "Crítica",
}


def to_evolution_number(phone: str | None) -> str:
    """Converte o telefone brasileiro salvo pela API para o formato do Baileys."""

    normalized = validate_optional_phone(phone)
    if not normalized:
        raise ValueError("recipient_phone_invalid")
    return f"55{normalized}"


def _shorten(value: str | None, max_length: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= max_length else f"{clean[: max_length - 3]}..."


def _level_label(value: str | None, fallback: str) -> str:
    return LEVEL_LABELS.get(str(value or "").lower(), fallback)


def build_ticket_message(notification: Notification) -> str:
    """Monta mensagem sem descrição, imagens ou outras informações sensíveis."""

    ticket = notification.ticket
    if not ticket:
        raise ValueError("ticket_not_found")

    ticket_url = f"{settings.WHATSAPP_FRONTEND_BASE_URL}/tickets/{ticket.id}"
    return "\n".join(
        (
            "HELP WEB HEALTH",
            "",
            notification.title,
            f"Chamado: CH-{ticket.id:06d}",
            f"Setor: {_shorten(ticket.sector, 30) or 'não informado'}",
            f"Categoria: {_shorten(ticket.category, 40) or 'não informada'}",
            f"Prioridade: {_level_label(ticket.priority, 'Não informada')}",
            f"Impacto: {_level_label(ticket.operational_impact, 'Não informado')}",
            "",
            f"Acesse: {ticket_url}",
        )
    )
