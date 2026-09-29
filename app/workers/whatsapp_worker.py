import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from app.core import security_policy as policy
from app.core.config import settings
from app.db.models.notification_delivery import NotificationDelivery
from app.db.session import SessionLocal
from app.services.messaging.evolution import send_text_message
from app.services.messaging.whatsapp import build_ticket_message, to_evolution_number
from app.services.notifications.queue import (
    build_notification_redis_client,
    enqueue_delivery,
    ensure_notification_consumer_group,
)


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _recover_expired_processing(db) -> int:
    now = _now()
    updated = (
        db.query(NotificationDelivery)
        .filter(
            NotificationDelivery.channel == "whatsapp",
            NotificationDelivery.status == "processing",
            NotificationDelivery.processing_until.is_not(None),
            NotificationDelivery.processing_until < now,
        )
        .update(
            {
                NotificationDelivery.status: "pending",
                NotificationDelivery.queued_at: None,
                NotificationDelivery.processing_until: None,
            },
            synchronize_session=False,
        )
    )
    if updated:
        db.commit()
    return int(updated or 0)


def enqueue_pending_deliveries(client, db) -> int:
    """Publica no Redis entregas persistidas que ainda não foram processadas."""

    now = _now()
    stale_before = now - timedelta(seconds=policy.WHATSAPP_QUEUE_LEASE_SECONDS)
    deliveries = (
        db.query(NotificationDelivery)
        .filter(
            NotificationDelivery.channel == "whatsapp",
            NotificationDelivery.status == "pending",
            NotificationDelivery.attempts < policy.WHATSAPP_MAX_ATTEMPTS,
            or_(
                NotificationDelivery.next_attempt_at.is_(None),
                NotificationDelivery.next_attempt_at <= now,
            ),
            or_(
                NotificationDelivery.queued_at.is_(None),
                NotificationDelivery.queued_at <= stale_before,
            ),
        )
        .order_by(NotificationDelivery.created_at.asc(), NotificationDelivery.id.asc())
        .limit(policy.WHATSAPP_WORKER_BATCH_SIZE)
        .all()
    )

    queued = 0
    for delivery in deliveries:
        try:
            enqueue_delivery(client, delivery.id)
            delivery.queued_at = now
            db.commit()
            queued += 1
        except Exception:
            db.rollback()
            logger.warning(
                "Falha ao enfileirar entrega WhatsApp | delivery_id=%s",
                delivery.id,
                exc_info=True,
            )
            break
    return queued


def _claim_delivery(db, delivery_id: int) -> bool:
    now = _now()
    lease_until = now + timedelta(seconds=policy.WHATSAPP_WORKER_LEASE_SECONDS)
    updated = (
        db.query(NotificationDelivery)
        .filter(
            NotificationDelivery.id == delivery_id,
            NotificationDelivery.channel == "whatsapp",
            NotificationDelivery.status == "pending",
            NotificationDelivery.attempts < policy.WHATSAPP_MAX_ATTEMPTS,
            or_(
                NotificationDelivery.next_attempt_at.is_(None),
                NotificationDelivery.next_attempt_at <= now,
            ),
        )
        .update(
            {
                NotificationDelivery.status: "processing",
                NotificationDelivery.attempts: NotificationDelivery.attempts + 1,
                NotificationDelivery.queued_at: None,
                NotificationDelivery.processing_until: lease_until,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return bool(updated)


def _mark_failed(db, delivery: NotificationDelivery, error_code: str) -> None:
    if delivery.attempts >= policy.WHATSAPP_MAX_ATTEMPTS:
        delivery.status = "failed"
        delivery.next_attempt_at = None
    else:
        delay = min(
            policy.WHATSAPP_RETRY_BASE_SECONDS * (2 ** max(delivery.attempts - 1, 0)),
            3600,
        )
        delivery.status = "pending"
        delivery.next_attempt_at = _now() + timedelta(seconds=delay)
    delivery.queued_at = None
    delivery.processing_until = None
    delivery.last_error = error_code[:240]
    db.commit()


def process_delivery(delivery_id: int) -> bool:
    """Processa uma entrega com claim atômico e tentativas limitadas."""

    db = SessionLocal()
    try:
        if not _claim_delivery(db, delivery_id):
            return False

        delivery = db.get(NotificationDelivery, delivery_id)
        if not delivery or not delivery.notification or not delivery.recipient:
            if delivery:
                _mark_failed(db, delivery, "delivery_reference_missing")
            return False

        try:
            number = to_evolution_number(delivery.recipient.phone)
            text = build_ticket_message(delivery.notification)
            provider_message_id = send_text_message(number=number, text=text)
        except Exception as exc:
            error_code = str(exc)[:240] or exc.__class__.__name__
            _mark_failed(db, delivery, error_code)
            logger.warning(
                "Entrega WhatsApp falhou | delivery_id=%s | attempt=%s | status=%s | error=%s",
                delivery.id,
                delivery.attempts,
                delivery.status,
                error_code,
            )
            return False

        delivery.status = "sent"
        delivery.provider_message_id = provider_message_id
        delivery.sent_at = _now()
        delivery.next_attempt_at = None
        delivery.queued_at = None
        delivery.processing_until = None
        delivery.last_error = None
        db.commit()
        logger.info(
            "Entrega WhatsApp concluída | delivery_id=%s | notification_id=%s | recipient_id=%s",
            delivery.id,
            delivery.notification_id,
            delivery.recipient_id,
        )
        return True
    finally:
        db.close()


def run_worker(*, once: bool = False) -> int:
    if not settings.whatsapp_configured:
        logger.error(
            "Worker WhatsApp não iniciado: configure WHATSAPP_ENABLED, Redis e Evolution API."
        )
        return 1

    client = build_notification_redis_client()
    ensure_notification_consumer_group(client)
    logger.info(
        "Worker WhatsApp iniciado | stream=%s | group=%s | consumer=%s",
        policy.REDIS_NOTIFICATION_STREAM,
        policy.REDIS_NOTIFICATION_GROUP,
        policy.REDIS_NOTIFICATION_CONSUMER,
    )

    while True:
        db = SessionLocal()
        try:
            recovered = _recover_expired_processing(db)
            queued = enqueue_pending_deliveries(client, db)
            if recovered or queued:
                logger.info(
                    "Fila WhatsApp atualizada | recuperadas=%s | enfileiradas=%s",
                    recovered,
                    queued,
                )
        finally:
            db.close()

        if once:
            return 0

        messages = client.xreadgroup(
            groupname=policy.REDIS_NOTIFICATION_GROUP,
            consumername=policy.REDIS_NOTIFICATION_CONSUMER,
            streams={policy.REDIS_NOTIFICATION_STREAM: ">"},
            count=policy.WHATSAPP_WORKER_BATCH_SIZE,
            block=max(1000, int(policy.WHATSAPP_WORKER_POLL_SECONDS * 1000)),
        )
        for _, entries in messages:
            for entry_id, values in entries:
                try:
                    delivery_id = int(values.get("delivery_id", "0"))
                    if delivery_id:
                        process_delivery(delivery_id)
                except (TypeError, ValueError):
                    logger.warning("Mensagem inválida na fila WhatsApp | stream_id=%s", entry_id)
                finally:
                    client.xack(policy.REDIS_NOTIFICATION_STREAM, policy.REDIS_NOTIFICATION_GROUP, entry_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker de notificações WhatsApp")
    parser.add_argument("--once", action="store_true", help="Enfileira uma vez e encerra")
    args = parser.parse_args()
    raise SystemExit(run_worker(once=args.once))


if __name__ == "__main__":
    logging.basicConfig(level=getattr(logging, policy.LOG_LEVEL.upper(), logging.INFO))
    main()
