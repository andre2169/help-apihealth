from pydantic import BaseModel, EmailStr, Field
from pydantic import field_validator

from app.schemas.validators import normalize_email_address, validate_password


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        # Login valida só o formato para evitar rejeitar email válido por falha DNS temporária.
        return normalize_email_address(value, check_deliverability=False)


class AccountRecoveryRequest(BaseModel):
    email: EmailStr
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_recovery_email(cls, value):
        return normalize_email_address(value, check_deliverability=False)

    @field_validator("new_password", mode="before")
    @classmethod
    def clean_recovery_password(cls, value):
        return validate_password(value)


class AccountRecoveryConfirm(BaseModel):
    email: EmailStr
    new_password: str = Field(min_length=8, max_length=128)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")

    @field_validator("email", mode="before")
    @classmethod
    def normalize_confirm_email(cls, value):
        return normalize_email_address(value, check_deliverability=False)

    @field_validator("new_password", mode="before")
    @classmethod
    def clean_confirm_recovery_password(cls, value):
        return validate_password(value)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
