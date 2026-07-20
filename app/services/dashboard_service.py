from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.db.models.user import User


def _visible_tickets_query(db: Session, current_user: User):
    query = db.query(Ticket)
    if current_user.role == "user":
        query = query.filter(Ticket.user_id == current_user.id)
    return query


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
        }
        for row in rows
    ]


def _start_of_day(value: date):
    return datetime.combine(value, time.min)


def _end_of_day(value: date):
    return datetime.combine(value, time.max)


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
        query = query.filter(Ticket.category == category)

    if sector:
        query = query.filter(Ticket.sector == sector)

    if operational_impact:
        query = query.filter(Ticket.operational_impact == operational_impact)

    return query


def _naive_utc(value):
    if not value:
        return None
    if value.tzinfo:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _sla_metrics(query):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    soon = now + timedelta(hours=4)
    active_statuses = ["open", "reopened", "in_progress"]

    overdue_count = (
        query.filter(
            Ticket.status.in_(active_statuses),
            Ticket.due_at.isnot(None),
            Ticket.due_at < now,
        )
        .count()
    )
    due_soon_count = (
        query.filter(
            Ticket.status.in_(active_statuses),
            Ticket.due_at.isnot(None),
            Ticket.due_at >= now,
            Ticket.due_at <= soon,
        )
        .count()
    )

    resolved_tickets = query.filter(Ticket.resolved_at.isnot(None)).all()
    resolution_minutes = []
    within_sla = 0

    for ticket in resolved_tickets:
        created_at = _naive_utc(ticket.created_at)
        resolved_at = _naive_utc(ticket.resolved_at)
        due_at = _naive_utc(ticket.due_at)
        if created_at and resolved_at:
            resolution_minutes.append(
                max(0, int((resolved_at - created_at).total_seconds() // 60))
            )
        if due_at and resolved_at and resolved_at <= due_at:
            within_sla += 1

    avg_resolution_minutes = (
        int(sum(resolution_minutes) / len(resolution_minutes))
        if resolution_minutes
        else 0
    )

    return {
        "overdue": overdue_count,
        "due_soon": due_soon_count,
        "resolved_total": len(resolved_tickets),
        "within_sla": within_sla,
        "avg_resolution_minutes": avg_resolution_minutes,
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
    buckets = {
        "Até 24h": 0,
        "1 a 3 dias": 0,
        "4 a 7 dias": 0,
        "Mais de 7 dias": 0,
    }

    tickets = query.filter(Ticket.status.in_(["open", "reopened", "in_progress"])).all()
    for ticket in tickets:
        created_at = _naive_utc(ticket.created_at)
        if not created_at:
            continue

        age_hours = max(0, (now - created_at).total_seconds() / 3600)
        if age_hours <= 24:
            buckets["Até 24h"] += 1
        elif age_hours <= 72:
            buckets["1 a 3 dias"] += 1
        elif age_hours <= 168:
            buckets["4 a 7 dias"] += 1
        else:
            buckets["Mais de 7 dias"] += 1

    return buckets


def _queue_snapshot(query):
    active_statuses = ["open", "reopened", "in_progress"]
    active_query = query.filter(Ticket.status.in_(active_statuses))

    return {
        "Ativos": active_query.count(),
        "Sem técnico": active_query.filter(Ticket.technician_id.is_(None)).count(),
        "Críticos ativos": active_query.filter(Ticket.operational_impact == "critical").count(),
        "Alta prioridade ativa": active_query.filter(
            Ticket.priority.in_(["high", "critical"])
        ).count(),
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

    total = query.count()
    by_status = _counts_by(query, Ticket.status)
    by_priority = _counts_by(query, Ticket.priority)
    by_category = _counts_by(query, Ticket.category)
    by_sector = _counts_by(query, Ticket.sector)
    by_operational_impact = _counts_by(query, Ticket.operational_impact)
    sla = _sla_metrics(query)

    recent_tickets = _ticket_summary_rows(
        query.order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .limit(6)
    )

    technician_queue = []
    my_active_tickets = []

    if current_user.role in ["technician", "admin"]:
        technician_queue = _ticket_summary_rows(
            db.query(Ticket)
            .filter(Ticket.status.in_(["open", "reopened"]))
            .order_by(Ticket.created_at.asc(), Ticket.id.asc())
            .limit(8)
        )

        my_active_tickets = _ticket_summary_rows(
            db.query(Ticket)
            .filter(
                Ticket.technician_id == current_user.id,
                Ticket.status == "in_progress",
            )
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
    category_counts = _counts_by(query, Ticket.category)
    sector_counts = _counts_by(query, Ticket.sector)
    equipment_counts = _counts_by(query, Ticket.equipment)
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
        technician_rows = (
            db.query(
                User.id,
                User.name,
                func.count(filtered_tickets.c.ticket_id).label("assigned_total"),
                func.sum(
                    case((filtered_tickets.c.ticket_status == "resolved", 1), else_=0)
                ).label("resolved_total"),
                func.sum(
                    case((filtered_tickets.c.ticket_status == "closed", 1), else_=0)
                ).label("closed_total"),
            )
            .outerjoin(filtered_tickets, filtered_tickets.c.technician_id == User.id)
            .filter(User.role.in_(["technician", "admin"]))
            .group_by(User.id, User.name)
            .order_by(User.name.asc())
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
