from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.core.dependencies import get_current_user
from app.core.permissions import require_user, require_technician, require_admin

from app.db.models.ticket import Ticket
from app.db.models.user import User

from app.schemas.ticket import TicketCreate, TicketResponse, TicketListResponse
from app.schemas.timeline import TimelineItem

from app.services import ticket_service
from app.services.timeline_service import get_ticket_timeline
from app.services.ticket_access_service import can_view_ticket_timeline
from app.schemas.enums import (
    SortDirection,
    TicketImpact,
    TicketOrderBy,
    TicketPriority,
    TicketStatus,
)
from app.schemas.validators import validate_short_text
from app.core.exceptions import (
    TicketNotFound,
    TicketInvalidStatus,
    TicketPermissionDenied,
)

router = APIRouter(prefix="/tickets", tags=["Tickets"])


def _http_error(exc: Exception):
    if isinstance(exc, TicketNotFound):
        raise HTTPException(status_code=404, detail=str(exc) or "Ticket não encontrado")
    if isinstance(exc, TicketInvalidStatus):
        raise HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, TicketPermissionDenied):
        raise HTTPException(status_code=403, detail=str(exc))
    raise exc


def _clean_optional_filter(value: str | None, field_name: str, max_length: int) -> str | None:
    try:
        return validate_short_text(value, field_name=field_name, max_length=max_length)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post("/", response_model=TicketResponse, response_model_exclude_none=True)
def create_ticket(
    ticket_in: TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    try:
        return ticket_service.create_ticket_service(
            db=db, ticket_in=ticket_in, current_user=current_user
        )
    except Exception as e:
        _http_error(e)


@router.patch("/{ticket_id}/assign", response_model=TicketResponse)
def assign_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_technician),
):
    try:
        return ticket_service.assign_ticket_service(
            db=db, ticket_id=ticket_id, current_user=current_user
        )
    except Exception as e:
        _http_error(e)


@router.patch("/{ticket_id}/resolve", response_model=TicketResponse)
def resolve_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_technician),
):
    try:
        return ticket_service.resolve_ticket_service(
            db=db, ticket_id=ticket_id, current_user=current_user
        )
    except Exception as e:
        _http_error(e)


@router.patch("/{ticket_id}/close", response_model=TicketResponse)
def close_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    try:
        return ticket_service.close_ticket_service(
            db=db, ticket_id=ticket_id, current_user=current_user
        )
    except Exception as e:
        _http_error(e)

@router.patch("/{ticket_id}/reopen", response_model=TicketResponse)
def reopen_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    return ticket_service.reopen_ticket_service(
        db=db,
        ticket_id=ticket_id,
        current_user=current_user,
    )


@router.delete("/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        ticket_service.delete_ticket_service(
            db=db,
            ticket_id=ticket_id,
            current_user=current_user,
        )
    except Exception as e:
        _http_error(e)



@router.get("/", response_model=TicketListResponse)
def list_tickets(
    status: TicketStatus | None = None,
    technician_id: int | None = Query(None, ge=1),
    user_id: int | None = Query(None, ge=1),
    priority: TicketPriority | None = None,
    category: str | None = Query(None, min_length=2, max_length=40),
    sector: str | None = Query(None, min_length=2, max_length=30),
    operational_impact: TicketImpact | None = None,
    order_by: TicketOrderBy = TicketOrderBy.created_at,
    direction: SortDirection = SortDirection.desc,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    return ticket_service.list_tickets_service(
        db=db,
        current_user=current_user,
        status=status.value if status else None,
        technician_id=technician_id,
        user_id=user_id,
        priority=priority.value if priority else None,
        category=_clean_optional_filter(category, "Categoria", 40),
        sector=_clean_optional_filter(sector, "Setor", 30),
        operational_impact=operational_impact.value if operational_impact else None,
        order_by=order_by.value,
        direction=direction.value,
        skip=skip,
        limit=limit,
    )


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    try:
        return ticket_service.get_ticket_service(
            db=db,
            ticket_id=ticket_id,
            current_user=current_user,
        )
    except Exception as e:
        _http_error(e)


@router.get("/{ticket_id}/timeline", response_model=List[TimelineItem])
def ticket_timeline(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket não encontrado")

    try:
        can_view_ticket_timeline(user=current_user, ticket=ticket)
        return get_ticket_timeline(db, ticket_id)
    except Exception as e:
        _http_error(e)
