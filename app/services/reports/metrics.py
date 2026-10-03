from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.db.models.user import User
from app.db.models.catalog_option import CatalogOption
from app.core.classification import classification_key
from app.services.reports.aggregation import activity_series, normalize_counts
from app.services.tickets.access import apply_ticket_personal_scope


def _visible_tickets_query(db: Session, current_user: User):
    return apply_ticket_personal_scope(db.query(Ticket), current_user)


def _counts_by(query, column):
    return {
        key or "Sem valor": total
        for key, total in query.with_entities(column, func.count(Ticket.id)).group_by(column).all()
    }


def _ticket_summary_rows(query):
    rows = query.with_entities(
        Ticket.id,
        Ticket.title,
        Ticket.category,
        Ticket.priority,
        Ticket.sector,
        Ticket.equipment,
        Ticket.operational_impact,
        Ticket.status,
        Ticket.technician_id,
        Ticket.created_at,
        Ticket.due_at,
        Ticket.sla_hours,
    ).all()

    return [
        {
            "id": row.id,
            "title": row.title,
            "category": row.category,
            "priority": row.priority,
            "sector": row.sector,
            "equipment": row.equipment,
            "operational_impact": row.operational_impact,
            "status": row.status,
            "technician_id": row.technician_id,
            "created_at": row.created_at,
            "due_at": row.due_at,
            "sla_hours": row.sla_hours,
        }
        for row in rows
    ]


def _start_of_day(value: date):
    return datetime.combine(value, time.min)


def _end_of_day(value: date):
    return datetime.combine(value, time.max)


def _classification_filter(query, column, value):
    key = classification_key(value)
    matches = [
        name for (name,) in query.with_entities(column).distinct().all()
        if classification_key(name) == key
    ]
    return query.filter(column.in_(matches))


def _apply_report_filters(
    query,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    sector: str | None = None,
    operational_impact: str | None = None,
):
    if start_date:
        query = query.filter(Ticket.created_at >= _start_of_day(start_date))

    if end_date:
        query = query.filter(Ticket.created_at <= _end_of_day(end_date))

    if status:
        query = query.filter(Ticket.status == status)

    if priority:
        query = query.filter(Ticket.priority == priority)

    if category:
        query = _classification_filter(query, Ticket.category, category)

    if sector:
        query = _classification_filter(query, Ticket.sector, sector)

    if operational_impact:
        query = query.filter(Ticket.operational_impact == operational_impact)

    return query


def _sla_metrics(query):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    soon = now + timedelta(hours=4)
    active_statuses = ["open", "reopened", "in_progress"]

    resolved_condition = and_(
        Ticket.created_at.isnot(None),
        Ticket.resolved_at.isnot(None),
    )
    within_sla_condition = and_(
        resolved_condition,
        Ticket.due_at.isnot(None),
        Ticket.resolved_at <= Ticket.due_at,
    )
    active_condition = Ticket.status.in_(active_statuses)

    # O banco calcula a duracao sem transferir todas as datas para Python.
    # PostgreSQL e SQLite usam funcoes diferentes para diferenca de datas.
    dialect_name = query.session.get_bind().dialect.name
    if dialect_name == "postgresql":
        elapsed_minutes = func.extract(
            "epoch", Ticket.resolved_at - Ticket.created_at
        ) / 60
    else:
        elapsed_minutes = (
            func.julianday(Ticket.resolved_at) - func.julianday(Ticket.created_at)
        ) * 1440

    row = query.with_entities(
        func.sum(
            case(
                (and_(active_condition, Ticket.due_at.isnot(None), Ticket.due_at < now), 1),
                else_=0,
            )
        ).label("overdue"),
        func.sum(
            case(
                (
                    and_(
                        active_condition,
                        Ticket.due_at.isnot(None),
                        Ticket.due_at >= now,
                        Ticket.due_at <= soon,
                    ),
                    1,
                ),
                else_=0,
            )
        ).label("due_soon"),
        func.sum(case((resolved_condition, 1), else_=0)).label("resolved_total"),
        func.sum(case((within_sla_condition, 1), else_=0)).label("within_sla"),
        func.avg(
            case(
                (resolved_condition, case((elapsed_minutes > 0, elapsed_minutes), else_=0)),
                else_=None,
            )
        ).label("avg_resolution_minutes"),
    ).one()

    return {
        "overdue": int(row.overdue or 0),
        "due_soon": int(row.due_soon or 0),
        "resolved_total": int(row.resolved_total or 0),
        "within_sla": int(row.within_sla or 0),
        "avg_resolution_minutes": int(row.avg_resolution_minutes or 0),
    }


def _daily_counts(query):
    return {
        str(day or "Sem data"): total
        for day, total in (
            query.with_entities(func.date(Ticket.created_at), func.count(Ticket.id))
            .group_by(func.date(Ticket.created_at))
            .order_by(func.date(Ticket.created_at).asc())
            .all()
        )
    }


def _requester_counts(query):
    rows = (
        query.join(User, User.id == Ticket.user_id)
        .with_entities(User.name, func.count(Ticket.id).label("total"))
        .group_by(User.id, User.name)
        .order_by(func.count(Ticket.id).desc(), User.name.asc())
        .limit(8)
        .all()
    )
    return {name or "Sem nome": int(total or 0) for name, total in rows}


def _active_age_counts(query):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    buckets = {"Até 24h": 0, "1 a 3 dias": 0, "4 a 7 dias": 0, "Mais de 7 dias": 0}
    day_bucket = case(
        (Ticket.created_at >= now - timedelta(hours=24), "Até 24h"),
        (Ticket.created_at >= now - timedelta(hours=72), "1 a 3 dias"),
        (Ticket.created_at >= now - timedelta(hours=168), "4 a 7 dias"),
        else_="Mais de 7 dias",
    )

    rows = (
        query.filter(
            Ticket.status.in_(["open", "reopened", "in_progress"]),
            Ticket.created_at.isnot(None),
        )
        .with_entities(day_bucket.label("bucket"), func.count(Ticket.id))
        .group_by(day_bucket)
        .all()
    )
    for bucket, total in rows:
        buckets[str(bucket)] = int(total or 0)

    return buckets


def _queue_snapshot(query):
    active_statuses = ["open", "reopened", "in_progress"]
    active_query = query.filter(Ticket.status.in_(active_statuses))
    row = active_query.with_entities(
        func.count(Ticket.id).label("active_total"),
        func.sum(case((Ticket.technician_id.is_(None), 1), else_=0)).label("unassigned"),
        func.sum(case((Ticket.operational_impact == "critical", 1), else_=0)).label("critical"),
        func.sum(case((Ticket.priority.in_(["high", "critical"]), 1), else_=0)).label("high_priority"),
    ).one()

    return {
        "Ativos": int(row.active_total or 0),
        "Sem técnico": int(row.unassigned or 0),
        "Críticos ativos": int(row.critical or 0),
        "Alta prioridade ativa": int(row.high_priority or 0),
    }


def _reopen_events_count(db: Session, query):
    filtered_tickets = query.with_entities(Ticket.id).subquery()
    return (
        db.query(TicketEvent)
        .filter(
            TicketEvent.ticket_id.in_(select(filtered_tickets.c.id)),
            TicketEvent.event_type == "REOPENED",
        )
        .count()
    )


def _percent(part: int, total: int) -> int:
    if total <= 0:
        return 0
    return round((part / total) * 100)


def _report_summary_metrics(*, status_counts: dict, sla: dict, queue_snapshot: dict, reopen_events_count: int):
    total_analyzed = sum(int(value or 0) for value in status_counts.values())
    active_total = (
        int(status_counts.get("open", 0) or 0)
        + int(status_counts.get("reopened", 0) or 0)
        + int(status_counts.get("in_progress", 0) or 0)
    )
    completed_total = int(status_counts.get("resolved", 0) or 0) + int(status_counts.get("closed", 0) or 0)
    sla_resolved_total = int(sla.get("resolved_total", 0) or 0)
    sla_within_total = int(sla.get("within_sla", 0) or 0)

    return {
        "total_analyzed": total_analyzed,
        "active_total": active_total,
        "completed_total": completed_total,
        "completed_percent": _percent(completed_total, total_analyzed),
        "sla_resolved_total": sla_resolved_total,
        "sla_within_total": sla_within_total,
        "sla_within_percent": _percent(sla_within_total, sla_resolved_total),
        "avg_resolution_hours": round(int(sla.get("avg_resolution_minutes", 0) or 0) / 60),
        "unassigned_active_total": int(queue_snapshot.get("Sem técnico", 0) or 0),
        "critical_active_total": int(queue_snapshot.get("Críticos ativos", 0) or 0),
        "high_priority_active_total": int(queue_snapshot.get("Alta prioridade ativa", 0) or 0),
        "reopen_events_count": int(reopen_events_count or 0),
    }


def dashboard_summary_service(*, db: Session, current_user: User):
    query = _visible_tickets_query(db, current_user)

    by_status = _counts_by(query, Ticket.status)
    by_priority = _counts_by(query, Ticket.priority)
    by_category = _counts_by(query, Ticket.category)
    by_sector = _counts_by(query, Ticket.sector)
    by_operational_impact = _counts_by(query, Ticket.operational_impact)
    total = sum(int(value or 0) for value in by_status.values())
    sla = _sla_metrics(query)

    recent_tickets = _ticket_summary_rows(
        query.order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .limit(6)
    )

    technician_queue = []
    my_active_tickets = []
    technician_queue_total = 0
    my_active_total = 0

    if current_user.role in ["technician", "admin"]:
        queue_query = db.query(Ticket).filter(
            Ticket.deleted_at.is_(None),
            Ticket.status.in_(["open", "reopened"]),
            Ticket.technician_id.is_(None),
        )
        my_query = db.query(Ticket).filter(
            Ticket.deleted_at.is_(None),
            Ticket.technician_id == current_user.id,
            Ticket.status == "in_progress",
        )
        technician_queue_total = queue_query.count()
        my_active_total = my_query.count()
        technician_queue = _ticket_summary_rows(
            queue_query
            .order_by(Ticket.created_at.asc(), Ticket.id.asc())
            .limit(8)
        )

        my_active_tickets = _ticket_summary_rows(
            my_query
            .order_by(Ticket.updated_at.desc(), Ticket.id.desc())
            .limit(8)
        )

    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "by_category": by_category,
        "by_sector": by_sector,
        "by_operational_impact": by_operational_impact,
        "sla": sla,
        "recent_tickets": recent_tickets,
        "technician_queue": technician_queue,
        "my_active_tickets": my_active_tickets,
        "technician_queue_total": technician_queue_total,
        "my_active_total": my_active_total,
    }


def reports_overview_service(
    *,
    db: Session,
    current_user: User,
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    sector: str | None = None,
    operational_impact: str | None = None,
):
    query = _visible_tickets_query(db, current_user)
    query = _apply_report_filters(
        query,
        start_date=start_date,
        end_date=end_date,
        status=status,
        priority=priority,
        category=category,
        sector=sector,
        operational_impact=operational_impact,
    )

    status_counts = _counts_by(query, Ticket.status)
    priority_counts = _counts_by(query, Ticket.priority)
    catalog = db.query(CatalogOption).all()
    category_counts = normalize_counts(
        _counts_by(query, Ticket.category), [item.name for item in catalog if item.kind == "category"],
    )
    sector_counts = normalize_counts(
        _counts_by(query, Ticket.sector), [item.name for item in catalog if item.kind == "sector"],
    )
    equipment_counts = normalize_counts(_counts_by(query, Ticket.equipment))
    impact_counts = _counts_by(query, Ticket.operational_impact)
    daily_counts = _daily_counts(query)
    requester_counts = _requester_counts(query)
    active_age_counts = _active_age_counts(query)
    queue_snapshot = _queue_snapshot(query)
    reopen_events_count = _reopen_events_count(db, query)
    sla = _sla_metrics(query)
    summary_metrics = _report_summary_metrics(
        status_counts=status_counts,
        sla=sla,
        queue_snapshot=queue_snapshot,
        reopen_events_count=reopen_events_count,
    )

    technician_rows = []
    if current_user.role in ["technician", "admin"]:
        filtered_tickets = query.with_entities(
            Ticket.id.label("ticket_id"),
            Ticket.status.label("ticket_status"),
            Ticket.technician_id.label("technician_id"),
        ).subquery()
        technician_query = db.query(
            User.id,
            User.name,
            func.count(filtered_tickets.c.ticket_id).label("assigned_total"),
            func.sum(
                case((filtered_tickets.c.ticket_status == "resolved", 1), else_=0)
            ).label("resolved_total"),
            func.sum(
                case((filtered_tickets.c.ticket_status == "closed", 1), else_=0)
            ).label("closed_total"),
        ).outerjoin(filtered_tickets, filtered_tickets.c.technician_id == User.id)

        if current_user.role == "admin":
            technician_query = technician_query.filter(User.role == "technician")
        else:
            technician_query = technician_query.filter(User.id == current_user.id)

        technician_rows = (
            technician_query
            .group_by(User.id, User.name)
            .order_by(func.count(filtered_tickets.c.ticket_id).desc(), User.name.asc(), User.id.asc())
            .all()
        )

    return {
        "status_counts": status_counts,
        "priority_counts": priority_counts,
        "category_counts": category_counts,
        "sector_counts": sector_counts,
        "equipment_counts": equipment_counts,
        "impact_counts": impact_counts,
        "daily_counts": daily_counts,
        "activity_series": activity_series(daily_counts, start_date=start_date, end_date=end_date),
        "non_technician_assigned_total": query.filter(
            Ticket.technician_id.isnot(None),
            ~Ticket.technician_id.in_(select(User.id).where(User.role == "technician")),
        ).count() if current_user.role == "admin" else 0,
        "requester_counts": requester_counts,
        "active_age_counts": active_age_counts,
        "queue_snapshot": queue_snapshot,
        "reopen_events_count": reopen_events_count,
        "summary_metrics": summary_metrics,
        "sla": sla,
        "filters": {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "status": status,
            "priority": priority,
            "category": category,
            "sector": sector,
            "operational_impact": operational_impact,
        },
        "generated_at": datetime.now(timezone.utc),
        "technicians": [
            {
                "id": row.id,
                "name": row.name,
                "assigned_total": int(row.assigned_total or 0),
                "resolved_total": int(row.resolved_total or 0),
                "closed_total": int(row.closed_total or 0),
            }
            for row in technician_rows
        ],
    }
