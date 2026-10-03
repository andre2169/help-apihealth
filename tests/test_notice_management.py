from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.audit_event import AuditEvent
from app.db.models.catalog_option import CatalogOption
from app.db.models.maintenance_notice import MaintenanceNotice
from .conftest import login


BASE = "/api/v1/admin/maintenance-notices"


def _data(**changes):
    return {"title": "Manutenção de rede", "message": "Rede em manutenção na unidade.",
            "severity": "warning", "target_sectors": ["Recepção"], "ends_at": None, **changes}


def _admin(client, db, user_factory):
    user = user_factory(email="notices.manager@gmail.com", role="admin")
    db.commit()
    login(client, user.email)
    return user


def _notice(db, actor, **changes):
    notice = MaintenanceNotice(**_data(), starts_at=datetime.now(timezone.utc) - timedelta(days=2),
                               created_by_id=actor.id)
    for field, value in changes.items():
        setattr(notice, field, value)
    db.add(notice)
    db.commit()
    return notice.id


@pytest.mark.parametrize("role", ["user", "technician"])
def test_notice_actions_require_admin_and_csrf(client, db, user_factory, role):
    path = f"{BASE}/9999"
    assert client.patch(path, json=_data()).status_code == 401
    assert client.delete(path).status_code == 401
    user = user_factory(email=f"notices.{role}@gmail.com", role=role)
    db.commit()
    login(client, user.email)
    assert client.patch(path, json=_data()).status_code == 403
    assert client.delete(path).status_code == 403
    admin = _admin(client, db, user_factory)
    notice_id = _notice(db, admin)
    client.headers.pop("X-CSRF-Token")
    assert client.patch(f"{BASE}/{notice_id}", json=_data()).status_code == 403
    assert client.patch(f"{BASE}/{notice_id}/active", json={"active": False}).status_code == 403
    assert client.delete(f"{BASE}/{notice_id}").status_code == 403


def test_notice_edit_preserves_publication_author_and_active_state(client, db, user_factory):
    admin = _admin(client, db, user_factory)
    author = user_factory(email="notices.author@gmail.com", role="admin")
    notice_id = _notice(db, author, active=False)
    original = db.get(MaintenanceNotice, notice_id)
    starts_at, created_at = original.starts_at, original.created_at
    ends_at = datetime.now(timezone.utc) + timedelta(days=3)
    response = client.patch(f"{BASE}/{notice_id}", json=_data(
        title="Manutenção revisada", message="Atualização do comunicado.", severity="critical",
        target_sectors=["RECEPCAO", "Recepção", "TI"], ends_at=ends_at.isoformat(),
    ))
    assert response.status_code == 200, response.text
    assert response.json()["target_sectors"] == ["Recepção", "TI"]
    assert response.json()["active"] is False
    db.expire_all()
    notice = db.get(MaintenanceNotice, notice_id)
    assert notice.created_by_id == author.id
    assert notice.starts_at == starts_at
    assert notice.created_at == created_at
    assert notice.severity == "critical"
    audit = db.query(AuditEvent).filter_by(action="admin.maintenance_notice_updated").one()
    assert audit.actor_id == admin.id
    assert "message" not in audit.details


@pytest.mark.parametrize("changes", [
    {"title": " "}, {"message": "X" * 501}, {"severity": "unknown"},
    {"ends_at": "2026-01-01T10:00:00"}, {"ends_at": "2000-01-01T10:00:00Z"},
    {"target_sectors": ["Setor inventado"]}, {"target_sectors": 42},
    {"target_sectors": "TI"}, {"target_sectors": [None]},
    {"active": True}, {"created_by_id": 999}, {"starts_at": "2026-01-01T10:00:00Z"},
])
def test_invalid_notice_updates_leave_record_unchanged(client, db, user_factory, changes):
    admin = _admin(client, db, user_factory)
    notice_id = _notice(db, admin)
    response = client.patch(f"{BASE}/{notice_id}", json=_data(**changes))
    assert response.status_code == 422, response.text
    db.expire_all()
    assert db.get(MaintenanceNotice, notice_id).title == "Manutenção de rede"
    assert db.query(AuditEvent).filter_by(action="admin.maintenance_notice_updated").count() == 0


def test_expired_notice_needs_new_deadline_before_activation(client, db, user_factory):
    admin = _admin(client, db, user_factory)
    notice_id = _notice(db, admin, active=False, ends_at=datetime.now(timezone.utc) - timedelta(days=1))
    path = f"{BASE}/{notice_id}"
    assert client.patch(f"{path}/active", json={"active": True}).status_code == 409
    db.expire_all()
    assert db.get(MaintenanceNotice, notice_id).active is False
    assert client.patch(path, json=_data(ends_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())).status_code == 200
    assert client.patch(f"{path}/active", json={"active": True}).status_code == 200
    assert notice_id in {item["id"] for item in client.get("/api/v1/maintenance-notices/").json()}
    assert client.patch(path, json=_data(ends_at=None)).json()["ends_at"] is None


def test_notice_edit_preserves_existing_inactive_sector_but_rejects_new_one(client, db, user_factory):
    admin = _admin(client, db, user_factory)
    notice_id = _notice(db, admin)
    for name in ("Recepção", "Radiologia"):
        db.query(CatalogOption).filter_by(kind="sector", name=name).one().active = False
    db.commit()
    assert client.patch(f"{BASE}/{notice_id}", json=_data()).status_code == 200
    assert client.patch(f"{BASE}/{notice_id}", json=_data(target_sectors=["Radiologia"])).status_code == 422
    assert client.post(f"{BASE}/", json=_data()).status_code == 422


def test_notice_delete_removes_only_selected_notice_and_retains_audit(client, db, user_factory):
    admin = _admin(client, db, user_factory)
    first = _notice(db, admin)
    second = _notice(db, admin, title="Outro comunicado")
    assert client.delete(f"{BASE}/{first}").status_code == 204
    assert first not in {item["id"] for item in client.get(f"{BASE}/").json()}
    assert second in {item["id"] for item in client.get("/api/v1/maintenance-notices/").json()}
    audit = db.query(AuditEvent).filter_by(action="admin.maintenance_notice_deleted").one()
    assert audit.target_id == first
    assert audit.actor_id == admin.id
    assert client.delete(f"{BASE}/{first}").status_code == 404
    assert client.patch(f"{BASE}/{first}", json=_data()).status_code == 404


def test_notice_create_normalizes_and_validates_official_sectors(client, db, user_factory):
    _admin(client, db, user_factory)
    response = client.post(f"{BASE}/", json=_data(target_sectors=["RECEPCAO", "Recepção"]))
    assert response.status_code == 201
    assert response.json()["target_sectors"] == ["Recepção"]
    assert client.post(f"{BASE}/", json=_data(target_sectors=["Inventado"])).status_code == 422
