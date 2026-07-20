from sqlalchemy import Boolean, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)

    # Dados de contato e contexto institucional do usuário.
    phone = Column(String(30), nullable=True)
    job_title = Column(String(80), nullable=True)
    department = Column(String(100), nullable=True)
    unit_name = Column(String(100), nullable=True)
    notification_preference = Column(String(20), nullable=False, default="email")

    # Segurança
    password_hash = Column(String, nullable=False)
    session_version = Column(Integer, nullable=False, default=1)
    email_verified = Column(Boolean, nullable=False, default=False, index=True)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)

    # user | technician | admin
    role = Column(String(20), default="user", index=True)

    # Imagem pequena em Data URL/base64 para o protótipo/TCC.
    avatar_image = Column(Text, nullable=True)

    # Datas
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now()
    )

    # Tickets criados pelo usuário
    tickets = relationship(
        "Ticket",
        back_populates="owner",
        foreign_keys="Ticket.user_id"
    )

    # Tickets atribuídos como técnico
    assigned_tickets = relationship(
        "Ticket",
        foreign_keys="Ticket.technician_id"
    )

    # Comentários feitos pelo usuário
    comments = relationship(
        "Comment",
        back_populates="author",
        cascade="all, delete-orphan"
    )

    verification_codes = relationship(
        "AccountVerification",
        back_populates="user",
        cascade="all, delete-orphan"
    )
