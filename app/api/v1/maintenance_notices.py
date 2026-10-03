from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.permissions import require_admin, require_user
from app.deps import get_db
from app.db.models.user import User
from app.db.models.maintenance_notice_read import MaintenanceNoticeRead
from app.schemas.maintenance_notice import (
    MaintenanceNoticeActiveUpdate,
    MaintenanceNoticeCreate,
    MaintenanceNoticeResponse,
    MaintenanceNoticeUpdate,
    MaintenanceNoticeReadRequest,
)
from app.services.audit.events import record_audit_event
from app.services.maintenance_notices import (
    create_notice,
    list_active_notices_for_user,
    list_admin_notices,
    update_notice_active,
    update_notice,
    get_notice,
    mark_notice_read,
)
from app.core.request_context import get_client_ip


router = APIRouter(prefix="/maintenance-notices", tags=["Maintenance notices"])
admin_router = APIRouter(
    prefix="/admin/maintenance-notices",
    tags=["Admin maintenance notices"],
    dependencies=[Depends(require_admin)],
)


@router.get("/", response_model=list[MaintenanceNoticeResponse])
def get_active_maintenance_notices(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    return list_active_notices_for_user(db=db, user=current_user)


@router.post("/{notice_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def read_maintenance_notice(
    data: MaintenanceNoticeReadRequest,
    notice_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    mark_notice_read(db=db, user=current_user, notice_id=notice_id, revision=data.revision)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/", response_model=list[MaintenanceNoticeResponse])
def get_admin_maintenance_notices(
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return list_admin_notices(db=db, limit=limit)


@admin_router.post(
    "/",
    response_model=MaintenanceNoticeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_maintenance_notice(
    data: MaintenanceNoticeCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    notice = create_notice(db=db, data=data, actor=current_user)
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="admin.maintenance_notice_created",
        target_type="maintenance_notice",
        target_id=notice.id,
        ip_address=get_client_ip(request),
        details={"severity": notice.severity, "audience": notice.audience, "target_sector_count": len(notice.target_sectors)},
    )
    db.commit()
    db.refresh(notice)
    return notice


@admin_router.patch("/{notice_id}/active", response_model=MaintenanceNoticeResponse)
def set_maintenance_notice_active(
    request: Request,
    notice_id: int = Path(..., ge=1),
    data: MaintenanceNoticeActiveUpdate = ...,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    notice = update_notice_active(db=db, notice_id=notice_id, active=data.active)
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="admin.maintenance_notice_activated" if data.active else "admin.maintenance_notice_deactivated",
        target_type="maintenance_notice",
        target_id=notice.id,
        ip_address=get_client_ip(request),
    )
    db.commit()
    db.refresh(notice)
    return notice


@admin_router.patch("/{notice_id}", response_model=MaintenanceNoticeResponse)
def edit_maintenance_notice(
    data: MaintenanceNoticeUpdate,
    request: Request,
    notice_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    notice = update_notice(db=db, notice_id=notice_id, data=data)
    record_audit_event(
        db, actor_id=current_user.id, action="admin.maintenance_notice_updated",
        target_type="maintenance_notice", target_id=notice.id, ip_address=get_client_ip(request),
        details={"severity": notice.severity, "audience": notice.audience, "target_sector_count": len(notice.target_sectors)},
    )
    db.commit()
    db.refresh(notice)
    return notice


@admin_router.delete("/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_maintenance_notice(
    request: Request,
    notice_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    notice = get_notice(db, notice_id)
    record_audit_event(
        db, actor_id=current_user.id, action="admin.maintenance_notice_deleted",
        target_type="maintenance_notice", target_id=notice.id, ip_address=get_client_ip(request),
        details={"severity": notice.severity, "audience": notice.audience, "target_sector_count": len(notice.target_sectors)},
    )
    db.delete(notice)
    db.query(MaintenanceNoticeRead).filter_by(notice_id=notice.id).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
