from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.models.maintenance_notice import MaintenanceNotice
from app.db.models.maintenance_notice_read import MaintenanceNoticeRead
from .conftest import login


PUBLIC = "/api/v1/maintenance-notices"
ADMIN = "/api/v1/admin/maintenance-notices"


def _account(client, db, user_factory, email="notice.reader@gmail.com", role="user", department="Recepção"):
    user = user_factory(email=email, role=role)
    user.department = department
    db.commit()
    login(client, user.email)
    return user


def _notice(db, **changes):
    notice = MaintenanceNotice(title="Rede indisponível", message="Manutenção programada.", severity="warning",
                               target_sectors=["Recepção"], starts_at=datetime.now(timezone.utc) - timedelta(days=1))
    for field, value in changes.items():
        setattr(notice, field, value)
    db.add(notice)
    db.commit()
    return notice.id


def _read(client, notice_id, revision=1):
    return client.post(f"{PUBLIC}/{notice_id}/read", json={"revision": revision})


def test_notice_read_persists_across_sessions_and_is_private_to_current_user(client, db, user_factory):
    first = _account(client, db, user_factory)
    notice_id = _notice(db)
    assert client.get(f"{PUBLIC}/").json()[0]["revision"] == 1
    assert _read(client, notice_id).status_code == 204
    assert client.get(f"{PUBLIC}/").json() == []
    new_session = TestClient(app)
    login(new_session, first.email)
    assert new_session.get(f"{PUBLIC}/").json() == []
    second_session = TestClient(app)
    second = _account(second_session, db, user_factory, email="notice.second@gmail.com")
    assert second_session.get(f"{PUBLIC}/").json()[0]["id"] == notice_id
    assert db.query(MaintenanceNoticeRead).count() == 1
    assert db.get(MaintenanceNoticeRead, (first.id, notice_id)).revision == 1
    assert db.get(MaintenanceNoticeRead, (second.id, notice_id)) is None


def test_mark_read_is_idempotent_without_changing_other_notices(client, db, user_factory):
    user = _account(client, db, user_factory)
    first, second = _notice(db), _notice(db)
    assert _read(client, first).status_code == 204
    receipt = db.get(MaintenanceNoticeRead, (user.id, first))
    original_date = receipt.read_at
    assert _read(client, first).status_code == 204
    db.expire_all()
    assert db.query(MaintenanceNoticeRead).count() == 1
    assert db.get(MaintenanceNoticeRead, (user.id, first)).read_at == original_date
    assert [item["id"] for item in client.get(f"{PUBLIC}/").json()] == [second]


def test_read_requires_authenticated_verified_user_and_csrf(client, db, user_factory):
    notice_id = _notice(db)
    assert _read(client, notice_id).status_code == 401
    _account(client, db, user_factory)
    client.headers.pop("X-CSRF-Token")
    assert _read(client, notice_id).status_code == 403
    assert db.query(MaintenanceNoticeRead).count() == 0


@pytest.mark.parametrize("changes", [
    {"target_sectors": ["Radiologia"]}, {"active": False},
    {"starts_at": datetime.now(timezone.utc) + timedelta(days=2)},
    {"ends_at": datetime.now(timezone.utc) - timedelta(hours=1)},
])
def test_read_obeys_notice_sector_and_visibility_without_exposing_other_notices(client, db, user_factory, changes):
    _account(client, db, user_factory)
    notice_id = _notice(db, **changes)
    assert _read(client, notice_id).status_code == 404
    assert client.get(f"{PUBLIC}/").json() == []
    assert db.query(MaintenanceNoticeRead).count() == 0


@pytest.mark.parametrize("role", ["admin", "technician", "user"])
def test_all_roles_can_mark_an_applicable_notice_read(client, db, user_factory, role):
    _account(client, db, user_factory, role=role, department="RECEPCAO")
    notice_id = _notice(db, severity="critical")
    assert [item["id"] for item in client.get(f"{PUBLIC}/").json()] == [notice_id]
    assert _read(client, notice_id).status_code == 204


def test_edited_content_appears_again_but_noop_and_activation_do_not_reset_reads(client, db, user_factory):
    admin = _account(client, db, user_factory, role="admin")
    notice_id = _notice(db)
    assert _read(client, notice_id).status_code == 204
    data = {"title": "Rede indisponível", "message": "Manutenção programada.", "severity": "warning", "target_sectors": ["RECEPCAO"], "ends_at": None}
    same = client.patch(f"{ADMIN}/{notice_id}", json=data)
    assert same.status_code == 200, same.text
    assert same.json()["revision"] == 1
    assert client.get(f"{PUBLIC}/").json() == []
    assert client.patch(f"{ADMIN}/{notice_id}/active", json={"active": False}).status_code == 200
    assert client.patch(f"{ADMIN}/{notice_id}/active", json={"active": True}).status_code == 200
    assert client.get(f"{PUBLIC}/").json() == []
    data["message"] = "Novo prazo para a manutenção."
    changed = client.patch(f"{ADMIN}/{notice_id}", json=data)
    assert changed.json()["revision"] == 2
    assert client.get(f"{PUBLIC}/").json()[0]["revision"] == 2
    assert _read(client, notice_id, 1).status_code == 409
    assert db.get(MaintenanceNoticeRead, (admin.id, notice_id)).revision == 1
    assert _read(client, notice_id, 2).status_code == 204
    db.expire_all()
    assert db.query(MaintenanceNoticeRead).count() == 1
    assert db.get(MaintenanceNoticeRead, (admin.id, notice_id)).revision == 2
    assert client.get(f"{PUBLIC}/").json() == []
    assert client.get(f"{ADMIN}/").json()[0]["id"] == notice_id


@pytest.mark.parametrize("change", [
    {"title": "Título revisado"}, {"severity": "critical"}, {"target_sectors": ["TI"]},
    {"ends_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
])
def test_material_notice_changes_create_a_new_version(client, db, user_factory, change):
    _account(client, db, user_factory, role="admin")
    notice_id = _notice(db)
    data = {"title": "Rede indisponível", "message": "Manutenção programada.", "severity": "warning", "target_sectors": ["Recepção"], "ends_at": None, **change}
    assert client.patch(f"{ADMIN}/{notice_id}", json=data).json()["revision"] == 2


@pytest.mark.parametrize("body", [{}, {"revision": 0}, {"revision": True}, {"revision": "1"}, {"revision": 1, "user_id": 999}])
def test_read_rejects_invalid_versions_and_cannot_target_another_user(client, db, user_factory, body):
    _account(client, db, user_factory)
    notice_id = _notice(db)
    assert client.post(f"{PUBLIC}/{notice_id}/read", json=body).status_code == 422
    assert db.query(MaintenanceNoticeRead).count() == 0


def test_deleting_notice_removes_read_receipts_and_unknown_notice_returns_404(client, db, user_factory):
    _account(client, db, user_factory, role="admin")
    notice_id = _notice(db)
    assert _read(client, notice_id).status_code == 204
    assert client.delete(f"{ADMIN}/{notice_id}").status_code == 204
    assert db.query(MaintenanceNoticeRead).count() == 0
    assert _read(client, notice_id).status_code == 404


@pytest.mark.parametrize("role,audience,visible", [
    ("user", "all", True), ("user", "users", True), ("user", "technicians", False),
    ("technician", "all", True), ("technician", "users", False), ("technician", "technicians", True),
    ("admin", "all", True), ("admin", "users", True), ("admin", "technicians", True),
])
def test_notice_audience_is_enforced_on_list_and_read(client, db, user_factory, role, audience, visible):
    _account(client, db, user_factory, role=role)
    notice_id = _notice(db, audience=audience)
    assert bool(client.get(f"{PUBLIC}/").json()) is visible
    assert _read(client, notice_id).status_code == (204 if visible else 404)
    assert db.query(MaintenanceNoticeRead).count() == (1 if visible else 0)


def test_audience_changes_are_versioned_and_invalid_audiences_are_rejected(client, db, user_factory):
    _account(client, db, user_factory, role="admin")
    notice_id = _notice(db)
    data = {"title": "Rede indisponível", "message": "Manutenção programada.", "severity": "warning", "target_sectors": ["Recepção"], "ends_at": None, "audience": "users"}
    response = client.patch(f"{ADMIN}/{notice_id}", json=data)
    assert response.status_code == 200
    assert response.json()["audience"] == "users"
    assert response.json()["revision"] == 2
    data["audience"] = "admin"
    assert client.patch(f"{ADMIN}/{notice_id}", json=data).status_code == 422
    assert client.post(f"{ADMIN}/", json=data).status_code == 422


def test_notice_audience_and_sector_restrictions_apply_together(client, db, user_factory):
    _account(client, db, user_factory, role="user", department="TI")
    notice_id = _notice(db, audience="users", target_sectors=["Recepção"])
    assert client.get(f"{PUBLIC}/").json() == []
    assert _read(client, notice_id).status_code == 404


def test_other_sectors_do_not_hide_applicable_notices_before_display_limit(client, db, user_factory):
    _account(client, db, user_factory, department="Recepção")
    now = datetime.now(timezone.utc)
    db.add_all([
        MaintenanceNotice(title="Aviso de outro setor", message="Comunicado restrito.", severity="critical",
                          target_sectors=["Radiologia"], starts_at=now - timedelta(minutes=index + 1))
        for index in range(70)
    ])
    applicable = _notice(db, severity="info")
    assert [item["id"] for item in client.get(f"{PUBLIC}/").json()] == [applicable]


def test_unread_filter_is_applied_before_the_fifty_notice_limit(client, db, user_factory):
    _account(client, db, user_factory)
    db.add_all([
        MaintenanceNotice(title="Aviso geral", message="Comunicado para a unidade.", severity="info",
                          target_sectors=[], starts_at=datetime.now(timezone.utc) - timedelta(minutes=index + 1))
        for index in range(60)
    ])
    db.commit()
    initial = client.get(f"{PUBLIC}/").json()
    assert len(initial) == 50
    first = initial[0]["id"]
    assert _read(client, first).status_code == 204
    after = client.get(f"{PUBLIC}/").json()
    assert len(after) == 50
    assert first not in {item["id"] for item in after}
    assert len({item["id"] for item in after} - {item["id"] for item in initial}) == 1


def test_deleting_account_cleans_only_its_read_receipts(client, db, user_factory):
    reader = _account(client, db, user_factory)
    notice_id = _notice(db)
    assert _read(client, notice_id).status_code == 204
    admin = _account(client, db, user_factory, email="notice.admin@gmail.com", role="admin")
    assert _read(client, notice_id).status_code == 204
    assert client.delete(f"/api/v1/admin/users/{reader.id}").status_code == 204
    db.expire_all()
    assert db.query(MaintenanceNoticeRead).count() == 1
    assert db.get(MaintenanceNoticeRead, (admin.id, notice_id)) is not None
