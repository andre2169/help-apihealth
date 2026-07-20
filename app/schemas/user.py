from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime
from typing import Optional

from app.schemas.validators import (
    normalize_email_address,
    validate_data_image,
    validate_name,
    validate_optional_phone,
    validate_password,
    validate_short_text,
)

class UserBase(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value):
        return validate_name(value)

    @field_validator("email", mode="before")
    @classmethod
    def clean_email(cls, value):
        return normalize_email_address(value, check_deliverability=True)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)
    phone: Optional[str] = Field(default=None, min_length=9, max_length=16)
    job_title: Optional[str] = Field(default=None, max_length=40)
    department: Optional[str] = Field(default=None, max_length=30)
    unit_name: Optional[str] = Field(default=None, max_length=80)

    @field_validator("password", mode="before")
    @classmethod
    def clean_password(cls, value):
        return validate_password(value)

    @field_validator("phone", mode="before")
    @classmethod
    def clean_phone(cls, value):
        return validate_optional_phone(value)

    @field_validator("job_title", mode="before")
    @classmethod
    def clean_job_title(cls, value):
        return validate_short_text(value, field_name="Cargo", max_length=40)

    @field_validator("department", mode="before")
    @classmethod
    def clean_department(cls, value):
        return validate_short_text(value, field_name="Setor", max_length=30)

    @field_validator("unit_name", mode="before")
    @classmethod
    def clean_unit_name(cls, value):
        return validate_short_text(value, field_name="Unidade", max_length=80)


class UserResponse(BaseModel):
    id: int
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    role: str
    email_verified: bool = False
    phone: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    unit_name: Optional[str] = None
    notification_preference: str = "email"
    avatar_image: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class UserAdminResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    email_verified: bool = False
    phone: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    unit_name: Optional[str] = None
    notification_preference: str = "email"
    avatar_image: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserAdminListResponse(BaseModel):
    id: int
    name: str
    email_masked: str
    role: str
    email_verified: bool = False
    job_title: Optional[str] = None
    department: Optional[str] = None
    unit_name: Optional[str] = None
    created_at: datetime


class UserAdminUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, min_length=9, max_length=16)
    job_title: Optional[str] = Field(default=None, max_length=40)
    department: Optional[str] = Field(default=None, max_length=30)
    unit_name: Optional[str] = Field(default=None, max_length=80)
    notification_preference: Optional[str] = Field(default=None, max_length=20)

    @field_validator("name", mode="before")
    @classmethod
    def clean_admin_name(cls, value):
        if value is None:
            return None
        return validate_name(value)

    @field_validator("email", mode="before")
    @classmethod
    def clean_admin_email(cls, value):
        if value is None:
            return None
        return normalize_email_address(value, check_deliverability=True)

    @field_validator("phone", mode="before")
    @classmethod
    def clean_admin_phone(cls, value):
        return validate_optional_phone(value)

    @field_validator("job_title", mode="before")
    @classmethod
    def clean_admin_job_title(cls, value):
        return validate_short_text(value, field_name="Cargo", max_length=40)

    @field_validator("department", mode="before")
    @classmethod
    def clean_admin_department(cls, value):
        return validate_short_text(value, field_name="Setor", max_length=30)

    @field_validator("unit_name", mode="before")
    @classmethod
    def clean_admin_unit_name(cls, value):
        return validate_short_text(value, field_name="Unidade", max_length=80)

    @field_validator("notification_preference", mode="before")
    @classmethod
    def clean_admin_notification_preference(cls, value):
        if value in (None, ""):
            return None
        if str(value) not in {"email", "whatsapp", "both"}:
            raise ValueError("Preferência de notificação inválida.")
        return str(value)


class UserProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    phone: Optional[str] = Field(default=None, min_length=9, max_length=16)
    job_title: Optional[str] = Field(default=None, max_length=40)
    department: Optional[str] = Field(default=None, max_length=30)
    unit_name: Optional[str] = Field(default=None, max_length=80)
    notification_preference: Optional[str] = Field(default=None, max_length=20)
    avatar_image: Optional[str] = Field(default=None, max_length=600_000)

    @field_validator("name", mode="before")
    @classmethod
    def clean_profile_name(cls, value):
        if value is None:
            return None
        return validate_name(value)

    @field_validator("phone", mode="before")
    @classmethod
    def clean_profile_phone(cls, value):
        return validate_optional_phone(value)

    @field_validator("job_title", mode="before")
    @classmethod
    def clean_profile_job_title(cls, value):
        return validate_short_text(value, field_name="Cargo", max_length=40)

    @field_validator("department", mode="before")
    @classmethod
    def clean_profile_department(cls, value):
        return validate_short_text(value, field_name="Setor", max_length=30)

    @field_validator("unit_name", mode="before")
    @classmethod
    def clean_profile_unit_name(cls, value):
        return validate_short_text(value, field_name="Unidade", max_length=80)

    @field_validator("notification_preference", mode="before")
    @classmethod
    def clean_profile_notification_preference(cls, value):
        if value in (None, ""):
            return None
        if str(value) not in {"email", "whatsapp", "both"}:
            raise ValueError("Preferência de notificação inválida.")
        return str(value)

    @field_validator("avatar_image", mode="before")
    @classmethod
    def clean_avatar_image(cls, value):
        if value == "":
            return ""
        return validate_data_image(value, field_name="Foto do perfil")


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password", mode="before")
    @classmethod
    def clean_new_password(cls, value):
        return validate_password(value)


class PasswordChangeConfirm(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")

    @field_validator("new_password", mode="before")
    @classmethod
    def clean_confirm_new_password(cls, value):
        return validate_password(value)


class EmailChangeRequest(BaseModel):
    new_email: EmailStr
    current_password: str = Field(min_length=1, max_length=128)

    @field_validator("new_email", mode="before")
    @classmethod
    def clean_new_email(cls, value):
        return normalize_email_address(value, check_deliverability=True)


class EmailChangeConfirm(BaseModel):
    new_email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")

    @field_validator("new_email", mode="before")
    @classmethod
    def clean_confirm_new_email(cls, value):
        return normalize_email_address(value, check_deliverability=True)


class EmailVerificationConfirm(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
