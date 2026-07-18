from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.base import Base


class TicketEvent(Base):
    __tablename__ = "ticket_events"

    id = Column(Integer, primary_key=True, index=True)

    ticket_id = Column(
        Integer,
        ForeignKey("tickets.id"),
        nullable=False,
        index=True,
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    event_type = Column(
        String,
        nullable=False,
        index=True,
    )

    from_status = Column(
        String,
        nullable=True
    )

    to_status = Column(
        String,
        nullable=True
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    # Relacionamentos
    ticket = relationship("Ticket", back_populates="events")
    user = relationship("User")
