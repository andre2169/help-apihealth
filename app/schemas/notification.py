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


class AdminNotificationEventResponse(BaseModel):
    id: int
    ticket_id: int
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    created_at: datetime


class AdminNotificationEventListResponse(BaseModel):
    items: list[AdminNotificationEventResponse]
    total: int | None = None
    skip: int
    limit: int
    has_more: bool = False


class AdminTicketEventSummary(BaseModel):
    ticket_id: int
    title: str
    status: str
    priority: str
    sector: str
    category: str
    owner_name: str | None = None
    technician_name: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    event_count: int
    last_event: AdminNotificationEventResponse | None = None


class AdminTicketEventSummaryListResponse(BaseModel):
    items: list[AdminTicketEventSummary]
    total: int | None = None
    skip: int
    limit: int
    has_more: bool = False
