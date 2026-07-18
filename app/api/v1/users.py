from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas.user import UserCreate, UserResponse

from app.services.user_service import create_user_service
from app.core.exceptions import UserAlreadyExists

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


def _http_error(exc: Exception):
    if isinstance(exc, UserAlreadyExists):
        raise HTTPException(
            status_code=400,
            detail="Não foi possível concluir o cadastro com os dados informados",
        )
    raise exc


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
):
    try:
        return create_user_service(
            db=db,
            user_in=user_in,
        )
    except Exception as e:
        _http_error(e)
