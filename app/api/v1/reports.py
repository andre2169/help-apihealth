from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.permissions import require_technician
from app.db.models.user import User
from app.deps import get_db
from app.schemas.enums import TicketImpact, TicketPriority, TicketStatus
from app.schemas.validators import validate_short_text
from app.services.dashboard_service import reports_overview_service


router = APIRouter(prefix="/reports", tags=["Reports"])
MAX_REPORT_RANGE_DAYS = 366


def _clean_optional_filter(value: str | None, field_name: str, max_length: int) -> str | None:
    try:
        return validate_short_text(value, field_name=field_name, max_length=max_length)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


def _validate_report_period(start_date: date | None, end_date: date | None) -> None:
    today = date.today()

    if start_date and start_date > today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Data inicial não pode ser futura.",
        )

    if end_date and end_date > today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Data final não pode ser futura.",
        )

    if bool(start_date) != bool(end_date):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Informe data inicial e data final para filtrar por período.",
        )

    if start_date and end_date:
        if end_date < start_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Data final não pode ser menor que a data inicial.",
            )

        if end_date - start_date > timedelta(days=MAX_REPORT_RANGE_DAYS):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="O período do relatório deve ter no máximo 366 dias.",
            )


@router.get("/overview")
def reports_overview(
    start_date: date | None = None,
    end_date: date | None = None,
    status: TicketStatus | None = None,
    priority: TicketPriority | None = None,
    category: str | None = Query(None, min_length=2, max_length=40),
    sector: str | None = Query(None, min_length=2, max_length=30),
    operational_impact: TicketImpact | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_technician),
):
    _validate_report_period(start_date, end_date)

    return reports_overview_service(
        db=db,
        current_user=current_user,
        start_date=start_date,
        end_date=end_date,
        status=status.value if status else None,
        priority=priority.value if priority else None,
        category=_clean_optional_filter(category, "Categoria", 40),
        sector=_clean_optional_filter(sector, "Setor", 30),
        operational_impact=operational_impact.value if operational_impact else None,
    )
