from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.core.permissions import require_user
from app.db.models.user import User
from app.deps import get_db
from app.schemas.notification import (
    NotificationListResponse,
    NotificationReadAllResponse,
    NotificationResponse,
)
from app.services.notification_service import (
    list_my_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)


router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/", response_model=NotificationListResponse)
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    return list_my_notifications(
        db=db,
        current_user=current_user,
        unread_only=unread_only,
        limit=limit,
    )


@router.patch("/read-all", response_model=NotificationReadAllResponse)
def read_all_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    return {"updated": mark_all_notifications_read(db=db, current_user=current_user)}


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def read_notification(
    notification_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    notification = mark_notification_read(
        db=db,
        notification_id=notification_id,
        current_user=current_user,
    )
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificação não encontrada",
        )
    return notification
