from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.classification import classification_key
from app.db.models.catalog_option import CatalogOption
from app.db.models.maintenance_notice import MaintenanceNotice
from app.db.models.ticket import Ticket
from app.db.models.user import User


def require_catalog_name(db: Session, *, kind: str, value: str) -> str:
    option = db.query(CatalogOption).filter(
        CatalogOption.kind == kind,
        CatalogOption.normalized_name == classification_key(value),
        CatalogOption.active.is_(True),
    ).with_for_update().first()
    if not option:
        label = "setor" if kind == "sector" else "categoria"
        raise HTTPException(
            status_code=422,
            detail=f"Selecione um {label} ativo da lista oficial. Se não encontrar, solicite o cadastro ao administrador.",
        )
    return option.name


def create_catalog_option(db: Session, data) -> CatalogOption:
    key = classification_key(data.name)
    if db.query(CatalogOption.id).filter(
        CatalogOption.kind == data.kind, CatalogOption.normalized_name == key,
    ).first():
        raise HTTPException(409, "Este nome já está cadastrado. Se estiver inativo, reative-o.")
    option = CatalogOption(kind=data.kind, name=" ".join(data.name.split()), normalized_name=key)
    db.add(option)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Este nome já está cadastrado.") from None
    return option


def get_catalog_option(db: Session, option_id: int) -> CatalogOption:
    option = db.query(CatalogOption).filter(CatalogOption.id == option_id).with_for_update().first()
    if not option:
        raise HTTPException(404, "Item não encontrado.")
    return option


def _matching_values(db: Session, column, key: str) -> list[str]:
    return [value for (value,) in db.query(column).distinct() if value and classification_key(value) == key]


def rename_catalog_option(db: Session, option: CatalogOption, name: str) -> dict:
    cleaned = " ".join(name.split())
    if option.kind == "sector" and len(cleaned) > 30:
        raise HTTPException(422, "Setor deve ter no máximo 30 caracteres.")
    key = classification_key(cleaned)
    if db.query(CatalogOption.id).filter(
        CatalogOption.kind == option.kind,
        CatalogOption.normalized_name == key,
        CatalogOption.id != option.id,
    ).first():
        raise HTTPException(409, "Este nome já está cadastrado.")

    previous_name, previous_key = option.name, option.normalized_name
    column = Ticket.sector if option.kind == "sector" else Ticket.category
    values = _matching_values(db, column, previous_key)
    option.name, option.normalized_name = cleaned, key
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Este nome já está cadastrado.") from None

    # Keep classifications coherent, including archived tickets, without editing their history.
    tickets_updated = db.query(Ticket).filter(column.in_(values)).update(
        {column: cleaned, Ticket.updated_at: Ticket.updated_at}, synchronize_session="fetch",
    ) if values else 0
    notices_updated = users_updated = 0
    if option.kind == "sector":
        for notice in db.query(MaintenanceNotice).all():
            if any(classification_key(value) == previous_key for value in notice.target_sectors or []):
                notice.target_sectors = [
                    cleaned if classification_key(value) == previous_key else value
                    for value in notice.target_sectors
                ]
                notices_updated += 1
        departments = _matching_values(db, User.department, previous_key)
        if departments:
            users_updated = db.query(User).filter(User.department.in_(departments)).update(
                {User.department: cleaned}, synchronize_session="fetch",
            )
    return {
        "kind": option.kind, "previous_name": previous_name, "name": cleaned,
        "tickets_updated": tickets_updated, "notices_updated": notices_updated,
        "users_updated": users_updated,
    }


def delete_catalog_option(db: Session, option: CatalogOption) -> None:
    key = option.normalized_name
    column = Ticket.sector if option.kind == "sector" else Ticket.category
    if _matching_values(db, column, key):
        raise HTTPException(409, "Este cadastro possui chamados vinculados, inclusive no histórico. Desative-o em vez de excluir.")
    if option.kind == "sector":
        if _matching_values(db, User.department, key) or any(
            classification_key(value) == key
            for (sectors,) in db.query(MaintenanceNotice.target_sectors)
            for value in sectors or []
        ):
            raise HTTPException(409, "Este setor está vinculado a perfis ou avisos. Desative-o em vez de excluir.")
    db.delete(option)
