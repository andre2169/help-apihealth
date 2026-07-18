from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.base import Base


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)

    content = Column(Text, nullable=False)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relacionamentos
    author = relationship("User", back_populates="comments")
    ticket = relationship("Ticket", back_populates="comments")
