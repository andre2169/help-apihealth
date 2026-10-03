from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer
from sqlalchemy.sql import func

from app.db.base import Base


class MaintenanceNoticeRead(Base):
    __tablename__ = "maintenance_notice_reads"
    __table_args__ = (Index("ix_maintenance_notice_reads_notice_id", "notice_id"),)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    notice_id = Column(Integer, ForeignKey("maintenance_notices.id", ondelete="CASCADE"), primary_key=True)
    revision = Column(Integer, nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
