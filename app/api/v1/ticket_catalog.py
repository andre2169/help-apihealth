from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy.orm import Session

from app.core.permissions import require_admin, require_user
from app.core.request_context import get_client_ip
from app.db.models.catalog_option import CatalogOption
from app.db.models.user import User
from app.deps import get_db
from app.schemas.catalog_option import CatalogOptionActiveUpdate, CatalogOptionCreate, CatalogOptionNameUpdate, CatalogOptionResponse
from app.services.audit.events import record_audit_event
from app.services.ticket_catalog import create_catalog_option, delete_catalog_option, get_catalog_option, rename_catalog_option


router = APIRouter(prefix="/ticket-catalog", tags=["Ticket catalog"])
admin_router = APIRouter(prefix="/admin/ticket-catalog", tags=["Admin ticket catalog"])


@router.get("/", response_model=list[CatalogOptionResponse])
def list_catalog(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    query = db.query(CatalogOption)
    if not include_inactive:
        query = query.filter(CatalogOption.active.is_(True))
    return query.order_by(CatalogOption.kind, CatalogOption.name).all()


@admin_router.post("/", response_model=CatalogOptionResponse, status_code=201)
def add_catalog_option(
    data: CatalogOptionCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    option = create_catalog_option(db, data)
    record_audit_event(
        db, actor_id=current_user.id, action="admin.ticket_catalog_created",
        target_type="ticket_catalog", target_id=option.id,
        ip_address=get_client_ip(request), details={"kind": option.kind},
    )
    db.commit()
    db.refresh(option)
    return option


@admin_router.patch("/{option_id}/active", response_model=CatalogOptionResponse)
def set_catalog_option_active(
    data: CatalogOptionActiveUpdate,
    request: Request,
    option_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    option = get_catalog_option(db, option_id)
    option.active = data.active
    record_audit_event(
        db, actor_id=current_user.id,
        action="admin.ticket_catalog_activated" if data.active else "admin.ticket_catalog_deactivated",
        target_type="ticket_catalog", target_id=option.id,
        ip_address=get_client_ip(request),
    )
    db.commit()
    db.refresh(option)
    return option


@admin_router.patch("/{option_id}", response_model=CatalogOptionResponse)
def edit_catalog_option(
    data: CatalogOptionNameUpdate,
    request: Request,
    option_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    option = get_catalog_option(db, option_id)
    details = rename_catalog_option(db, option, data.name)
    record_audit_event(
        db, actor_id=current_user.id, action="admin.ticket_catalog_renamed",
        target_type="ticket_catalog", target_id=option.id,
        ip_address=get_client_ip(request), details=details,
    )
    db.commit()
    db.refresh(option)
    return option


@admin_router.delete("/{option_id}", status_code=204)
def remove_catalog_option(
    request: Request,
    option_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    option = get_catalog_option(db, option_id)
    details = {"kind": option.kind, "name": option.name}
    delete_catalog_option(db, option)
    record_audit_event(
        db, actor_id=current_user.id, action="admin.ticket_catalog_deleted",
        target_type="ticket_catalog", target_id=option_id,
        ip_address=get_client_ip(request), details=details,
    )
    db.commit()
    return Response(status_code=204)
