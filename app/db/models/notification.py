from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    recipient_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ticket_id = Column(
        Integer,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    type = Column(String(80), nullable=False, index=True)
    title = Column(String(140), nullable=False)
    message = Column(String(280), nullable=False)
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)

    recipient = relationship("User", foreign_keys=[recipient_id])
    actor = relationship("User", foreign_keys=[actor_id])
    ticket = relationship("Ticket")
