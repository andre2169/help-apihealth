from enum import Enum


class TicketStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"
    reopened = "reopened"


class TicketPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TicketImpact(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TicketOrderBy(str, Enum):
    id = "id"
    created_at = "created_at"
    due_at = "due_at"
    status = "status"
    priority = "priority"
    operational_impact = "operational_impact"


class SortDirection(str, Enum):
    asc = "asc"
    desc = "desc"
