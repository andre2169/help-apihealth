from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class NotificationDelivery(Base):
    """Outbox durável para entregas externas de uma notificação.

    A linha permanece no PostgreSQL mesmo quando o Redis ou a Evolution API
    estão indisponíveis. O worker pode então reenfileirar a entrega sem perder
    o evento e sem fazer o usuário repetir a ação no chamado.
    """

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "notification_id",
            "recipient_id",
            "channel",
            name="uq_notification_delivery_recipient_channel",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(
        Integer,
        ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel = Column(String(20), nullable=False, default="whatsapp", index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True, index=True)
    queued_at = Column(DateTime(timezone=True), nullable=True, index=True)
    processing_until = Column(DateTime(timezone=True), nullable=True, index=True)
    provider_message_id = Column(String(120), nullable=True)
    last_error = Column(String(240), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    notification = relationship("Notification", back_populates="deliveries")
    recipient = relationship("User")
