from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.permissions import require_technician
from app.db.models.user import User
from app.deps import get_db
from app.services.dashboard_service import dashboard_summary_service


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_technician),
):
    return dashboard_summary_service(db=db, current_user=current_user)
