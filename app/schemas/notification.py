from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    id: int
    type: str
    title: str
    message: str
    ticket_id: int | None = None
    is_read: bool
    created_at: datetime
    read_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    unread_count: int


class NotificationReadAllResponse(BaseModel):
    updated: int
