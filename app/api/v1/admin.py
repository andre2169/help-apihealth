from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.db.models.user import User
from app.schemas.user import UserAdminResponse, UserAdminUpdate

from app.core.permissions import require_admin
from app.core.exceptions import TicketPermissionDenied

from app.services.admin_service import (
    list_users_service,
    get_user_service,
    change_user_role_service,
    update_user_service,
    delete_user_service,
)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
)


def _http_error(exc: Exception):
    if isinstance(exc, TicketPermissionDenied):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    raise exc


@router.get(
    "/users",
    response_model=list[UserAdminResponse],
)
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return list_users_service(db=db)


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
    response_model=UserAdminResponse,
)
def change_user_role(
    user_id: int,
    role: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        return change_user_role_service(
            db=db,
            user_id=user_id,
            role=role,
        )
    except Exception as e:
        _http_error(e)


@router.patch(
    "/users/{user_id}",
    response_model=UserAdminResponse,
)
def update_user(
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
        )
    except Exception as e:
        _http_error(e)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        delete_user_service(
            db=db,
            user_id=user_id,
            current_user=current_user,
        )
    except Exception as e:
        _http_error(e)
