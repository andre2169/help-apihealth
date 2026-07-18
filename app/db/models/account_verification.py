from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class AccountVerification(Base):
    __tablename__ = "account_verifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # purpose separa fluxos diferentes usando a mesma tabela: senha, email etc.
    purpose = Column(String(40), nullable=False, index=True)
    target_value = Column(String(255), nullable=True, index=True)

    # O código puro nunca é salvo no banco. Guardamos apenas o hash.
    code_hash = Column(String(128), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="verification_codes")
