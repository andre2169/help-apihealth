from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel



class TimelineAuthor(BaseModel):
    id: int
    name: str
    role: str
    avatar_image: Optional[str] = None


class TimelineItem(BaseModel):
    id: int
    type: Literal["event", "comment"]
    created_at: datetime

    # event
    event_type: Optional[str] = None
    from_status: Optional[str] = None
    to_status: Optional[str] = None

    # comment
    content: Optional[str] = None

    author: TimelineAuthor

    class Config:
        exclude_none = True
