from sqlalchemy import func

from app.db.models.comment import Comment
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.db.models.user import User
from tools.seed_shard_demo_data import create_demo_dataset


def test_demo_seed_adds_only_common_users_tickets_and_history(db, user_factory):
    existing_admin = user_factory(email="existing-admin@test.local", role="admin", name="Admin existente")
    baseline_users = db.query(func.count(User.id)).scalar()

    result = create_demo_dataset(
        db,
        user_count=5,
        ticket_count=25,
        run_id="teste-1234",
        seed=17,
        administrators=[existing_admin],
    )

    assert result["users"] == 5
    assert result["tickets"] == 25
    assert result["comments"] == 8
    assert result["events"] > result["tickets"]
    assert db.query(func.count(User.id)).scalar() == baseline_users + 5
    assert db.query(User).filter(User.email.like("demo.shard.teste-1234.%")).count() == 5
    assert db.query(User).filter(User.email.like("demo.shard.teste-1234.%"), User.role != "user").count() == 0
    assert db.query(func.count(Ticket.id)).scalar() == 25
    assert db.query(func.count(Comment.id)).scalar() == 8
    assert db.query(func.count(TicketEvent.id)).scalar() == result["events"]
    assert db.query(Ticket).filter(Ticket.issue_image.is_not(None)).count() == 0
    assert db.query(Ticket).filter(Ticket.status == "open").count() > 0
    assert db.query(Ticket).filter(Ticket.status == "in_progress").count() > 0
    assert db.query(Ticket).filter(Ticket.status == "resolved").count() > 0
    assert db.query(Ticket).filter(Ticket.status == "closed").count() > 0
    assert db.query(Ticket).filter(Ticket.status == "reopened").count() > 0


def test_demo_seed_rejects_duplicate_run_id(db):
    from tools.seed_shard_demo_data import ensure_run_is_unused

    user = User(
        name="Demo existente",
        email="demo.shard.duplicado.user001@example.com",
        password_hash="unused-test-hash",
        role="user",
    )
    db.add(user)
    db.flush()

    try:
        ensure_run_is_unused(db, "duplicado")
    except ValueError as exc:
        assert "Escolha outro identificador" in str(exc)
    else:
        raise AssertionError("Uma carga repetida deveria ser recusada")


def test_demo_seed_validates_run_id_and_limits(db):
    import pytest

    with pytest.raises(ValueError, match="identificador"):
        create_demo_dataset(db, user_count=1, ticket_count=1, run_id="x")

    with pytest.raises(ValueError, match="usuarios"):
        create_demo_dataset(db, user_count=201, ticket_count=1, run_id="limite-1")


def test_database_url_is_consumed_from_temporary_environment(monkeypatch):
    import os

    from tools.seed_shard_demo_data import _get_remote_database_url

    monkeypatch.setenv(
        "HELPWEB_DEMO_DATABASE_URL",
        "postgresql://seed-user:dummy-test-secret@db.example.invalid:5432/helpweb",
    )

    database_url, host = _get_remote_database_url()

    assert host == "db.example.invalid"
    assert "sslmode=require" in database_url
    assert "HELPWEB_DEMO_DATABASE_URL" not in os.environ


def test_seed_reads_only_minimum_fields_for_existing_event_actors(
    db, user_factory, query_statements
):
    from tools.seed_shard_demo_data import load_existing_event_actors

    user_factory(email="existing-tech@test.local", role="technician")
    user_factory(email="existing-admin@test.local", role="admin")

    technicians, administrators = load_existing_event_actors(db)

    assert len(technicians) == 1
    assert len(administrators) == 1
    actor_queries = [statement.lower() for statement in query_statements if "from users" in statement.lower()]
    assert actor_queries
    assert all("password_hash" not in statement for statement in actor_queries)
