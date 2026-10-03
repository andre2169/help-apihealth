from calendar import monthrange
from datetime import date, timedelta
from math import ceil

from app.core.classification import classification_key


def normalize_counts(counts: dict, official_names=()) -> dict:
    canonical = {classification_key(name): name for name in official_names}
    groups = {}
    # Stable spelling for legacy names; only accents, case and spaces are equivalent.
    for name in sorted(counts, key=lambda value: (classification_key(value), str(value))):
        key = classification_key(name)
        label = canonical.get(key) or " ".join(str(name or "Sem valor").split())
        group = groups.setdefault(key, [label, 0])
        group[1] += int(counts[name] or 0)
    return {label: total for label, total in groups.values()}


def _month_end(value: date) -> date:
    return value.replace(day=monthrange(value.year, value.month)[1])


def activity_series(daily_counts: dict, *, start_date=None, end_date=None, max_points=8) -> dict:
    values = {}
    undated = 0
    for key, count in daily_counts.items():
        try:
            day = date.fromisoformat(str(key))
        except ValueError:
            undated += int(count or 0)
            continue
        values[day] = values.get(day, 0) + int(count or 0)

    if not values:
        return {"title": "Evolução no período", "counts": {}, "undated_total": undated}
    start = start_date or min(values)
    end = end_date or max(values)
    span = (end - start).days + 1
    months = (end.year - start.year) * 12 + end.month - start.month + 1
    quarters = (end.year - start.year) * 4 + (end.month - 1) // 3 - (start.month - 1) // 3 + 1
    years = end.year - start.year + 1

    if span <= max_points:
        grain, title = "day", "Evolução por dia"
    elif ceil((span + start.weekday()) / 7) <= max_points:
        grain, title = "week", "Evolução por semana"
    elif months <= max_points:
        grain, title = "month", "Evolução por mês"
    elif quarters <= max_points:
        grain, title = "quarter", "Evolução por trimestre"
    else:
        grain, title = "year", "Evolução por ano"
    year_step = max(1, ceil(years / max_points))
    if grain == "year" and year_step > 1:
        title = "Evolução por intervalo de anos"

    def bucket(day):
        if grain == "day":
            return day
        if grain == "week":
            return day - timedelta(days=day.weekday())
        if grain == "month":
            return day.replace(day=1)
        if grain == "quarter":
            return day.replace(month=((day.month - 1) // 3) * 3 + 1, day=1)
        year = start.year + ((day.year - start.year) // year_step) * year_step
        return date(year, 1, 1)

    def bucket_end(first):
        if grain == "day":
            return first
        if grain == "week":
            return first + timedelta(days=6)
        if grain == "month":
            return _month_end(first)
        if grain == "quarter":
            return _month_end(first.replace(month=first.month + 2))
        return date(min(9999, first.year + year_step - 1), 12, 31)

    totals = {}
    cursor = bucket(start)
    while cursor <= end:
        totals[cursor] = 0
        last = bucket_end(cursor)
        if last >= end:
            break
        cursor = last + timedelta(days=1)
    for day, count in values.items():
        if start <= day <= end:
            key = bucket(day)
            totals[key] = totals.get(key, 0) + count

    counts = {}
    for first, count in totals.items():
        if grain == "day":
            label = first.strftime("%d/%m/%Y")
        elif grain == "week":
            lower, upper = max(start, first), min(end, bucket_end(first))
            label = f"{lower:%d/%m/%Y} a {upper:%d/%m/%Y}"
        elif grain == "month":
            label = first.strftime("%m/%Y")
        elif grain == "quarter":
            label = f"{(first.month - 1) // 3 + 1}º trimestre/{first.year}"
        else:
            last_year = min(end.year, first.year + year_step - 1)
            label = str(first.year) if year_step == 1 else f"{first.year} a {last_year}"
        counts[label] = count
    return {
        "title": title, "granularity": grain, "counts": counts,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "undated_total": undated,
    }
