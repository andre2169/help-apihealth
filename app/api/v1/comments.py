from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.core.permissions import require_user
from app.core.dependencies import get_current_user

from app.schemas.comment import CommentCreate, CommentResponse
from app.db.models.user import User

from app.services.comment_service import create_comment_service
from app.core.exceptions import (
    TicketNotFound,
    TicketInvalidStatus,
    TicketPermissionDenied,
)

router = APIRouter(
    prefix="/tickets/{ticket_id}/comments",
    tags=["Comments"],
)


def _http_error(exc: Exception):
    if isinstance(exc, TicketNotFound):
        raise HTTPException(
            status_code=404,
            detail="Ticket não encontrado",
        )
    if isinstance(exc, TicketInvalidStatus):
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )
    if isinstance(exc, TicketPermissionDenied):
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        )
    raise exc


@router.post(
    "/",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
def create_comment(
    ticket_id: int,
    comment_in: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    try:
        return create_comment_service(
            db=db,
            ticket_id=ticket_id,
            content=comment_in.content,
            current_user=current_user,
        )
    except Exception as e:
        _http_error(e)
