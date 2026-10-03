from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.validators import validate_long_text, validate_short_text
from app.core.classification import classification_key


def _utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Informe data e hora com fuso horário.")
    return value.astimezone(timezone.utc)


class MaintenanceNoticeFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=100)
    message: str = Field(min_length=3, max_length=500)
    severity: Literal["info", "warning", "critical"] = "warning"
    audience: Literal["all", "users", "technicians"] = "all"
    target_sectors: list[str] = Field(default_factory=list, max_length=12)
    ends_at: datetime | None = None

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value):
        return validate_short_text(value, field_name="Título", required=True, max_length=100)

    @field_validator("message", mode="before")
    @classmethod
    def clean_message(cls, value):
        return validate_long_text(value, field_name="Mensagem", required=True, max_length=500)

    @field_validator("target_sectors", mode="before")
    @classmethod
    def clean_sectors(cls, values):
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("Informe uma lista de setores válidos.")
        normalized = []
        seen = set()
        for value in values or []:
            sector = validate_short_text(value, field_name="Setor", required=True, max_length=30)
            key = classification_key(sector)
            if key not in seen:
                seen.add(key)
                normalized.append(sector)
        return normalized

    @field_validator("ends_at")
    @classmethod
    def require_timezone(cls, value):
        return _utc_datetime(value)


class MaintenanceNoticeCreate(MaintenanceNoticeFields):
    starts_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("starts_at")
    @classmethod
    def require_start_timezone(cls, value):
        return _utc_datetime(value)

    @model_validator(mode="after")
    def validate_window(self):
        if self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("O fim do aviso deve ocorrer depois do início.")
        return self


class MaintenanceNoticeUpdate(MaintenanceNoticeFields):
    pass


class MaintenanceNoticeActiveUpdate(BaseModel):
    active: bool


class MaintenanceNoticeReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)


class MaintenanceNoticeResponse(BaseModel):
    id: int
    title: str
    message: str
    severity: str
    audience: str
    target_sectors: list[str]
    starts_at: datetime
    ends_at: datetime | None = None
    active: bool
    revision: int
    created_at: datetime
    created_by_name: str | None = None

    model_config = ConfigDict(from_attributes=True)
