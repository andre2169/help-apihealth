from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional

from app.schemas.validators import validate_long_text

class CommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=250)
    ticket_id: Optional[int] = None

    @field_validator("content", mode="before")
    @classmethod
    def clean_content(cls, value):
        return validate_long_text(value, field_name="Comentário", required=True, max_length=250)


class CommentResponse(BaseModel):
    id: int
    content: str
    user_id: int
    ticket_id: int
    created_at: datetime

    class Config:
        from_attributes = True
