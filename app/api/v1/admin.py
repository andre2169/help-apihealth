from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.db.models.user import User
from app.schemas.user import (
    UserAdminListPage,
    UserAdminListResponse,
    UserAdminResponse,
    UserAdminUpdate,
)
from app.schemas.enums import SortDirection, UserOrderBy, UserRole
from app.schemas.validators import validate_short_text
from app.schemas.notification import (
    AdminNotificationEventListResponse,
    AdminTicketEventSummaryListResponse,
)
from app.schemas.ticket import DeletedTicketListResponse, TicketResponse

from app.core.permissions import require_admin
from app.core import security_policy as policy
from app.core.config import settings
from app.core.exceptions import TicketPermissionDenied
from app.core.request_context import get_client_ip, mask_email

from app.services.users.admin import (
    list_users_service,
    get_user_service,
    change_user_role_service,
    update_user_service,
    delete_user_service,
)
from app.services.notifications.service import (
    list_admin_notification_events,
    list_admin_ticket_event_summaries,
)
from app.services.tickets.deleted import (
    get_deleted_ticket_service,
    list_deleted_tickets_service,
    restore_deleted_ticket_service,
)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)

PROXY_DEBUG_HEADERS = (
    "x-forwarded-for",
    "x-real-ip",
    "cf-connecting-ip",
    "forwarded",
)


def _http_error(exc: Exception):
    if isinstance(exc, TicketPermissionDenied):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    raise exc


@router.get("/network-debug")
def network_debug(
    request: Request,
    current_user: User = Depends(require_admin),
):
    """
    Mostra somente informacoes de rede necessarias para diagnosticar proxy/IP.

    A rota e restrita a administradores e nao retorna cookies, Authorization
    nem outros headers sensiveis. Use temporariamente para confirmar se a
    hospedagem envia IP real por X-Forwarded-For, X-Real-IP ou CF-Connecting-IP.
    """
    if not policy.ENABLE_NETWORK_DEBUG_ENDPOINT:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurso nao encontrado.",
        )

    headers = {
        header_name: request.headers.get(header_name)
        for header_name in PROXY_DEBUG_HEADERS
    }

    return {
        "request_client_host": request.client.host if request.client else None,
        "resolved_client_ip": get_client_ip(request),
        "trusted_proxy_hops": settings.TRUSTED_PROXY_HOPS,
        "proxy_headers": headers,
    }


@router.get(
    "/users",
    response_model=UserAdminListPage,
)
def list_users(
    search: str | None = Query(None, min_length=1, max_length=80),
    role: UserRole | None = Query(None),
    is_active: bool | None = Query(None),
    order_by: UserOrderBy = UserOrderBy.name,
    direction: SortDirection = SortDirection.asc,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        clean_search = validate_short_text(search, field_name="Busca", max_length=80)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    return list_users_service(
        db=db,
        search=clean_search,
        role=role.value if role else None,
        is_active=is_active,
        order_by=order_by.value,
        direction=direction.value,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/notification-events",
    response_model=AdminNotificationEventListResponse,
)
def list_notification_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Consulta todos os eventos para administração, sem criar destinatário admin."""

    return list_admin_notification_events(db=db, skip=skip, limit=limit)


@router.get(
    "/ticket-events",
    response_model=AdminTicketEventSummaryListResponse,
)
def list_ticket_event_summaries(
    search: str | None = Query(None, min_length=1, max_length=80),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Lista chamados acompanhados por eventos, com pesquisa administrativa."""

    try:
        clean_search = validate_short_text(search, field_name="Busca", max_length=80)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    return list_admin_ticket_event_summaries(
        db=db,
        search=clean_search,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/deleted-tickets",
    response_model=DeletedTicketListResponse,
)
def list_deleted_tickets(
    search: str | None = Query(None, min_length=1, max_length=80),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Lista chamados excluídos logicamente para recuperação administrativa."""

    try:
        clean_search = validate_short_text(search, field_name="Busca", max_length=80)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    return list_deleted_tickets_service(
        db=db,
        current_user=current_user,
        search=clean_search,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/deleted-tickets/{ticket_id}",
    response_model=TicketResponse,
)
def get_deleted_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Retorna detalhes de um chamado excluído, somente para administradores."""

    return get_deleted_ticket_service(
        db=db, ticket_id=ticket_id, current_user=current_user
    )


@router.post(
    "/deleted-tickets/{ticket_id}/restore",
    response_model=TicketResponse,
)
def restore_deleted_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Recupera um chamado excluído logicamente e registra a auditoria."""

    return restore_deleted_ticket_service(
        db=db,
        ticket_id=ticket_id,
        current_user=current_user,
    )


@router.get(
    "/users/{user_id}",
    response_model=UserAdminResponse,
)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        return get_user_service(db=db, user_id=user_id)
    except Exception as e:
        _http_error(e)


@router.patch(
    "/users/{user_id}/role",
    response_model=UserAdminListResponse,
)
def change_user_role(
    request: Request,
    user_id: int,
    role: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        user = change_user_role_service(
            db=db,
            user_id=user_id,
            role=role,
            actor=current_user,
            ip_address=get_client_ip(request),
        )
        return {
            "id": user.id,
            "name": user.name,
            "email_masked": mask_email(user.email),
             "role": user.role,
             "email_verified": bool(user.email_verified),
             "is_active": bool(user.is_active),
            "job_title": user.job_title,
            "department": user.department,
            "unit_name": user.unit_name,
            "created_at": user.created_at,
        }
    except Exception as e:
        _http_error(e)


@router.patch(
    "/users/{user_id}",
    response_model=UserAdminResponse,
)
def update_user(
    request: Request,
    user_id: int,
    user_in: UserAdminUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        return update_user_service(
            db=db,
            user_id=user_id,
            name=user_in.name,
            email=user_in.email,
            phone=user_in.phone,
            job_title=user_in.job_title,
            department=user_in.department,
            unit_name=user_in.unit_name,
             notification_preference=user_in.notification_preference,
             is_active=user_in.is_active,
             actor=current_user,
            ip_address=get_client_ip(request),
        )
    except Exception as e:
        _http_error(e)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        delete_user_service(
            db=db,
            user_id=user_id,
            current_user=current_user,
            ip_address=get_client_ip(request),
        )
    except Exception as e:
        _http_error(e)
