import secrets

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.notification_delivery import NotificationDelivery
from app.deps import get_db
import logging


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

DELIVERED_STATUSES = {"SERVER_ACK", "DELIVERY_ACK", "READ", "PLAYED", "DELIVERED"}
FAILED_STATUSES = {"ERROR", "FAILED", "REJECTED"}


def _find_provider_id(value: object) -> str | None:
    if isinstance(value, dict):
        key = value.get("key")
        if isinstance(key, dict) and key.get("id"):
            return str(key["id"])[:120]
        for key_name in ("messageId", "message_id"):
            if value.get(key_name) and isinstance(value.get(key_name), (str, int)):
                return str(value[key_name])[:120]
        for child in value.values():
            found = _find_provider_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_provider_id(child)
            if found:
                return found
    return None


def _find_status(value: object) -> str | None:
    if isinstance(value, dict):
        for key in ("status", "ack", "messageStatus"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate.upper()
        for child in value.values():
            found = _find_status(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_status(child)
            if found:
                return found
    return None


@router.post("/evolution", status_code=status.HTTP_204_NO_CONTENT)
async def evolution_webhook(
    request: Request,
    x_evolution_webhook_secret: str | None = Header(default=None),
    x_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Atualiza somente o status de entregas; não processa respostas do WhatsApp."""

    # O webhook não usa JWT de navegador, mas sempre exige segredo próprio.
    supplied_secret = x_evolution_webhook_secret or x_webhook_secret or ""
    expected_secret = settings.EVOLUTION_WEBHOOK_SECRET or ""
    if not expected_secret:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    if not secrets.compare_digest(supplied_secret, expected_secret):
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        payload = await request.json()
    except ValueError:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    provider_id = _find_provider_id(payload)
    provider_status = _find_status(payload)
    if not provider_id or not provider_status:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    delivery = (
        db.query(NotificationDelivery)
        .filter(
            NotificationDelivery.channel == "whatsapp",
            NotificationDelivery.provider_message_id == provider_id,
        )
        .first()
    )
    if not delivery:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if provider_status in DELIVERED_STATUSES:
        delivery.status = "sent"
        delivery.last_error = None
    elif provider_status in FAILED_STATUSES:
        delivery.status = "failed"
        delivery.last_error = "provider_delivery_failed"
    else:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    delivery.processing_until = None
    delivery.queued_at = None
    db.commit()
    logger.info(
        "Status da entrega WhatsApp atualizado | delivery_id=%s | provider_status=%s",
        delivery.id,
        provider_status,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
