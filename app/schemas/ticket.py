from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
from typing import Optional

from app.schemas.enums import TicketImpact, TicketPriority
from app.schemas.validators import (
    validate_asset_tag,
    validate_data_image,
    validate_data_images,
    validate_long_text,
    validate_short_text,
)


class TicketBase(BaseModel):
    title: str = Field(min_length=3, max_length=100)
    description: str = Field(min_length=5, max_length=1000)
    category: str = Field(default="Infraestrutura", min_length=2, max_length=40)
    priority: TicketPriority = TicketPriority.medium
    sector: str = Field(default="Recepção", min_length=2, max_length=30)
    equipment: Optional[str] = Field(default=None, max_length=30)
    asset_tag: Optional[str] = Field(default=None, max_length=40)
    operational_impact: TicketImpact = TicketImpact.medium
    issue_image: Optional[str] = Field(default=None, max_length=1_500_000)
    issue_images: list[str] = Field(default_factory=list, max_length=3)
    sla_hours: Optional[int] = Field(default=None, ge=1, le=720)

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value):
        return validate_short_text(value, field_name="Título", required=True, max_length=100)

    @field_validator("description", mode="before")
    @classmethod
    def clean_description(cls, value):
        return validate_long_text(value, field_name="Descrição", required=True, max_length=1000)

    @field_validator("category", mode="before")
    @classmethod
    def clean_category(cls, value):
        return validate_short_text(value, field_name="Categoria", required=True, max_length=40)

    @field_validator("sector", mode="before")
    @classmethod
    def clean_sector(cls, value):
        return validate_short_text(value, field_name="Setor", required=True, max_length=30)

    @field_validator("equipment", mode="before")
    @classmethod
    def clean_equipment(cls, value):
        return validate_short_text(value, field_name="Equipamento", max_length=30)

    @field_validator("asset_tag", mode="before")
    @classmethod
    def clean_asset_tag(cls, value):
        return validate_asset_tag(value, max_length=40)

    @field_validator("issue_image", mode="before")
    @classmethod
    def clean_issue_image(cls, value):
        return validate_data_image(value, field_name="Foto do problema")

    @field_validator("issue_images", mode="before")
    @classmethod
    def clean_issue_images(cls, value):
        return validate_data_images(value, field_name="Fotos do problema")


class TicketCreate(TicketBase):
    pass


class TicketResponse(TicketBase):
    id: int
    status: str
    user_id: int
    technician_id: Optional[int]
    owner_name: Optional[str] = None
    technician_name: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime]
    due_at: Optional[datetime]
    resolved_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class TicketListItemResponse(BaseModel):
    id: int
    title: str
    category: str
    priority: str
    sector: str
    equipment: Optional[str] = None
    operational_impact: str
    status: str
    technician_id: Optional[int] = None
    owner_name: Optional[str] = None
    technician_name: Optional[str] = None
    created_at: datetime
    due_at: Optional[datetime] = None


class TicketListResponse(BaseModel):
    items: list[TicketListItemResponse]
    total: int
    skip: int
    limit: int
