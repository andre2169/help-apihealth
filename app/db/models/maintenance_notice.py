from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class MaintenanceNotice(Base):
    __tablename__ = "maintenance_notices"
    __table_args__ = (
        Index("ix_maintenance_notices_starts_at", "starts_at"),
        Index("ix_maintenance_notices_ends_at", "ends_at"),
        Index("ix_maintenance_notices_active", "active"),
        Index("ix_maintenance_notices_active_window", "active", "starts_at", "ends_at"),
        Index("ix_maintenance_notices_created_by_id", "created_by_id"),
    )

    id = Column(Integer, primary_key=True)
    title = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String(20), nullable=False, default="warning")
    audience = Column(String(20), nullable=False, default="all", server_default="all")
    target_sectors = Column(JSON, nullable=False, default=list)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    created_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    created_by_user = relationship("User", foreign_keys=[created_by_id])

    @property
    def created_by_name(self):
        return self.created_by_user.name if self.created_by_user else None
