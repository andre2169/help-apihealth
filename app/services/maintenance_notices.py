from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import case, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.models.maintenance_notice import MaintenanceNotice
from app.db.models.maintenance_notice_read import MaintenanceNoticeRead
from app.db.models.user import User
from app.db.models.catalog_option import CatalogOption
from app.core.classification import classification_key


def _notice_sectors(db: Session, sectors: list[str], previous: list[str] | None = None) -> list[str]:
    official = {
        option.normalized_name: option.name
        for option in db.query(CatalogOption).filter_by(kind="sector", active=True)
    }
    existing = {classification_key(value): value for value in previous or []}
    normalized = {}
    for sector in sectors:
        key = classification_key(sector)
        name = official.get(key) or existing.get(key)
        if not name:
            raise HTTPException(422, "Selecione setores ativos da lista oficial.")
        normalized[key] = name
    return list(normalized.values())


def get_notice(db: Session, notice_id: int) -> MaintenanceNotice:
    notice = db.query(MaintenanceNotice).filter_by(id=notice_id).with_for_update().first()
    if not notice:
        raise HTTPException(404, "Aviso não encontrado.")
    return notice


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _in_user_sector(notice: MaintenanceNotice, user: User) -> bool:
    return (user.role in {"admin", "technician"} or not user.department or not notice.target_sectors
            or classification_key(user.department) in {classification_key(sector) for sector in notice.target_sectors})


def _in_notice_audience(notice: MaintenanceNotice, user: User) -> bool:
    return (user.role == "admin" or (notice.audience == "all" and user.role in {"user", "technician"})
            or (notice.audience == "users" and user.role == "user")
            or (notice.audience == "technicians" and user.role == "technician"))


def list_active_notices_for_user(*, db: Session, user: User) -> list[MaintenanceNotice]:
    now = datetime.now(timezone.utc)
    rows = (
        db.query(MaintenanceNotice)
        .options(joinedload(MaintenanceNotice.created_by_user))
        .filter(
            MaintenanceNotice.active.is_(True),
            MaintenanceNotice.starts_at <= now,
            or_(MaintenanceNotice.ends_at.is_(None), MaintenanceNotice.ends_at > now),
            MaintenanceNotice.audience.in_(
                ["all", "users", "technicians"] if user.role == "admin" else
                ["all", "users"] if user.role == "user" else ["all", "technicians"]
            ),
            ~db.query(MaintenanceNoticeRead.user_id).filter(
                MaintenanceNoticeRead.notice_id == MaintenanceNotice.id,
                MaintenanceNoticeRead.user_id == user.id,
                MaintenanceNoticeRead.revision == MaintenanceNotice.revision,
            ).exists(),
        )
        .order_by(
            case(
                (MaintenanceNotice.severity == "critical", 1),
                (MaintenanceNotice.severity == "warning", 2),
                else_=3,
            ),
            MaintenanceNotice.starts_at.desc(),
            MaintenanceNotice.id.desc(),
        )
        .yield_per(100)
    )

    visible = []
    for notice in rows:
        if _in_user_sector(notice, user) and _in_notice_audience(notice, user):
            visible.append(notice)
            if len(visible) == 50:
                break
    return visible


def mark_notice_read(*, db: Session, user: User, notice_id: int, revision: int) -> None:
    notice = get_notice(db, notice_id)
    now = datetime.now(timezone.utc)
    if (not notice.active or _utc(notice.starts_at) > now
            or (notice.ends_at and _utc(notice.ends_at) <= now) or not _in_user_sector(notice, user)
            or not _in_notice_audience(notice, user)):
        raise HTTPException(404, "Aviso não encontrado.")
    if notice.revision != revision:
        raise HTTPException(409, "Este aviso foi atualizado. Leia a nova versão antes de marcá-lo como lido.")
    key = (user.id, notice.id)
    receipt = db.get(MaintenanceNoticeRead, key)
    if receipt is None:
        # A savepoint makes duplicate requests safe on SQLite as well as PostgreSQL.
        try:
            with db.begin_nested():
                db.add(MaintenanceNoticeRead(user_id=user.id, notice_id=notice.id, revision=revision, read_at=now))
                db.flush()
        except IntegrityError:
            receipt = db.get(MaintenanceNoticeRead, key)
            if receipt is None:
                raise
    if receipt is not None and receipt.revision < revision:
        receipt.revision = revision
        receipt.read_at = now
    db.flush()


def list_admin_notices(*, db: Session, limit: int = 100) -> list[MaintenanceNotice]:
    return (
        db.query(MaintenanceNotice)
        .options(joinedload(MaintenanceNotice.created_by_user))
        .order_by(MaintenanceNotice.starts_at.desc(), MaintenanceNotice.id.desc())
        .limit(min(max(limit, 1), 100))
        .all()
    )


def create_notice(
    *,
    db: Session,
    data,
    actor: User,
) -> MaintenanceNotice:
    notice = MaintenanceNotice(
        title=data.title,
        message=data.message,
        severity=data.severity,
        audience=data.audience,
        target_sectors=_notice_sectors(db, data.target_sectors),
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        active=True,
        created_by_id=actor.id,
    )
    db.add(notice)
    db.flush()
    db.refresh(notice)
    return notice


def update_notice_active(
    *,
    db: Session,
    notice_id: int,
    active: bool,
) -> MaintenanceNotice:
    notice = get_notice(db, notice_id)
    if active and notice.ends_at and _utc(notice.ends_at) <= datetime.now(timezone.utc):
        raise HTTPException(409, "Este aviso já encerrou. Edite a data de encerramento antes de ativá-lo.")
    notice.active = active
    db.flush()
    db.refresh(notice)
    return notice


def update_notice(*, db: Session, notice_id: int, data) -> MaintenanceNotice:
    notice = get_notice(db, notice_id)
    if data.ends_at and data.ends_at <= _utc(notice.starts_at):
        raise HTTPException(422, "O fim do aviso deve ocorrer depois do início.")
    sectors = _notice_sectors(db, data.target_sectors, notice.target_sectors)
    changed = (notice.title != data.title or notice.message != data.message or notice.severity != data.severity
               or notice.audience != data.audience
               or {classification_key(sector) for sector in sectors} != {
                   classification_key(sector) for sector in notice.target_sectors
               }
               or (data.ends_at != (_utc(notice.ends_at) if notice.ends_at else None)))
    if changed:
        notice.revision += 1
    notice.title = data.title
    notice.message = data.message
    notice.severity = data.severity
    notice.audience = data.audience
    notice.target_sectors = sectors
    notice.ends_at = data.ends_at
    db.flush()
    db.refresh(notice)
    return notice
