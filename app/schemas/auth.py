from pydantic import BaseModel, EmailStr, Field
from pydantic import field_validator

from app.schemas.validators import normalize_email_address


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        # Login valida só o formato para evitar rejeitar email válido por falha DNS temporária.
        return normalize_email_address(value, check_deliverability=False)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
