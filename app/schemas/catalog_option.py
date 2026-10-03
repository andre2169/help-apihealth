from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.validators import validate_short_text


class CatalogOptionCreate(BaseModel):
    kind: Literal["sector", "category"]
    name: str = Field(min_length=2, max_length=40)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value):
        return validate_short_text(value, field_name="Nome", required=True, max_length=40)

    @model_validator(mode="after")
    def check_sector_length(self):
        if self.kind == "sector" and len(self.name) > 30:
            raise ValueError("Setor deve ter no máximo 30 caracteres.")
        return self


class CatalogOptionActiveUpdate(BaseModel):
    active: bool


class CatalogOptionNameUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=40)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value):
        return validate_short_text(value, field_name="Nome", required=True, max_length=40)


class CatalogOptionResponse(BaseModel):
    id: int
    kind: str
    name: str
    active: bool
    model_config = ConfigDict(from_attributes=True)
