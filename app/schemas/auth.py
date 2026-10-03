import re
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

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
    new_password: str = Field(min_length=10, max_length=128)

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
    new_password: str = Field(min_length=10, max_length=128)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")

    @field_validator("email", mode="before")
    @classmethod
    def normalize_confirm_email(cls, value):
        return normalize_email_address(value, check_deliverability=False)

    @field_validator("new_password", mode="before")
    @classmethod
    def clean_confirm_recovery_password(cls, value):
        return validate_password(value)


class LoginResponse(BaseModel):
    status: Literal["ok", "verification_required"] = "ok"
    token_type: Literal["cookie"] | None = "cookie"
    challenge_id: str | None = None
    delivery: Literal["email", "log"] | None = None
    expires_in_minutes: int | None = None
    message: str | None = None


class LoginMFAConfirm(BaseModel):
    challenge_id: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    code: str = Field(min_length=6, max_length=14)

    @field_validator("code", mode="before")
    @classmethod
    def validate_mfa_code(cls, value):
        value = str(value or "").strip().upper()
        if not re.fullmatch(r"(?:\d{6}|[A-F0-9]{4}(?:-[A-F0-9]{4}){2})", value):
            raise ValueError("Informe o código de acesso ou um código de recuperação válido.")
        return value


class MFARecoveryCodeGenerate(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
