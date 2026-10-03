from sqlalchemy import Boolean, CheckConstraint, Column, Integer, String, UniqueConstraint

from app.db.base import Base


class CatalogOption(Base):
    __tablename__ = "ticket_catalog_options"
    __table_args__ = (
        UniqueConstraint("kind", "normalized_name", name="uq_ticket_catalog_kind_name"),
        CheckConstraint("kind IN ('sector', 'category')", name="ck_ticket_catalog_kind"),
    )

    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False)
    name = Column(String(40), nullable=False)
    normalized_name = Column(String(120), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
