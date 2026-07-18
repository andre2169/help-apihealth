from fastapi import Depends, HTTPException, status
from app.core.dependencies import get_current_user
from app.db.models.user import User


def require_user(
    current_user: User = Depends(get_current_user)
):
    return current_user


def require_technician(
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ["technician", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas técnicos e administradores podem executar esta ação"
        )
    return current_user


def require_admin(
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores"
        )
    return current_user
