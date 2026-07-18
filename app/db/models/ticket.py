from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(40), nullable=False, default="Geral", index=True)
    priority = Column(String(20), nullable=False, default="medium", index=True)
    sector = Column(String(30), nullable=False, default="Recepção", index=True)
    equipment = Column(String(30), nullable=True, index=True)
    asset_tag = Column(String(40), nullable=True)
    operational_impact = Column(String(20), nullable=False, default="medium", index=True)
    issue_image = Column(Text, nullable=True)
    issue_images = Column(JSON, nullable=True)
    sla_hours = Column(Integer, nullable=False, default=24)
    due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # open | in_progress | resolved | closed | reopened
    status = Column(String(20), nullable=False, default="open", index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    technician_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relacionamentos

    # Usuário que criou o ticket
    owner = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="tickets"
    )

    # Usuário técnico atribuído ao ticket
    technician = relationship(
        "User",
        foreign_keys=[technician_id],
        back_populates="assigned_tickets"
    )

    # Comentários do ticket
    comments = relationship(
        "Comment",
        back_populates="ticket",
        cascade="all, delete-orphan"
    )
   
    # Se apagar um ticket o evento some
    events = relationship(
       "TicketEvent",
       back_populates="ticket",
       cascade="all, delete-orphan"
    )

    @property
    def owner_name(self):
        return self.owner.name if self.owner else None

    @property
    def technician_name(self):
        return self.technician.name if self.technician else None
