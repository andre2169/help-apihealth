"""Gera dados ficticios para validar o HelpWeb Health localmente.

Este arquivo e uma ferramenta de desenvolvimento. Ele recusa qualquer banco
que nao seja SQLite para reduzir o risco de inserir dados de demonstracao na
hospedagem ou no PostgreSQL de producao.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import inspect, or_

from app.core.config import settings
from app.core.security import hash_password
from app.db.models.account_verification import AccountVerification
from app.db.models.audit_event import AuditEvent
from app.db.models.comment import Comment
from app.db.models.notification import Notification
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.db.models.token_blocklist import TokenBlocklist
from app.db.models.user import User
from app.db.session import SessionLocal, engine
from app.db.url import normalize_database_url


DEMO_PREFIX = "DEMO-"
LEGACY_DEMO_PREFIX = "[DEMO] "
# example.com e reservado para exemplos e passa pela validacao de email sem
# apontar para uma caixa real de producao.
DEMO_EMAIL_DOMAIN = "@example.com"
LEGACY_DEMO_EMAIL_DOMAIN = "@helpweb.test"
DEMO_PASSWORD = "DemoSenha123!"
DEFAULT_TICKET_COUNT = 200
DEFAULT_TECHNICIAN_COUNT = 8
DEFAULT_REQUESTER_COUNT = 30

FIRST_NAMES = [
    "Ana",
    "Bruno",
    "Camila",
    "Daniel",
    "Eduarda",
    "Felipe",
    "Gabriela",
    "Henrique",
    "Isabela",
    "Joao",
    "Larissa",
    "Marcos",
    "Natalia",
    "Otavio",
    "Paula",
    "Rafael",
    "Sabrina",
    "Thiago",
    "Vanessa",
    "William",
]

LAST_NAMES = [
    "Almeida",
    "Barbosa",
    "Cardoso",
    "Dias",
    "Ferreira",
    "Gomes",
    "Lima",
    "Mendes",
    "Nunes",
    "Oliveira",
    "Pereira",
    "Ramos",
    "Santos",
    "Silva",
    "Souza",
]

UNITS = [
    "UBS Centro",
    "UPA Municipal",
    "Hospital Regional",
    "Laboratorio Municipal",
    "Unidade da Familia",
    "Policlinica",
    "Secretaria de Saude",
    "CAPS Municipal",
]

SECTORS = [
    "Recepcao",
    "Enfermagem",
    "Farmacia",
    "Laboratorio",
    "Administrativo",
    "TI",
    "Arquivo",
    "Consultorios",
]

CATEGORIES = [
    "Rede",
    "Hardware",
    "Impressao",
    "Acesso",
    "Software hospitalar",
    "Infraestrutura",
]

EQUIPMENT = [
    "Computador",
    "Impressora",
    "Switch",
    "Roteador",
    "Leitor de codigo",
    "Sistema interno",
    "Telefone IP",
]

TICKET_CASES = [
    ("Impressora nao imprime documentos", "A impressora parou de responder durante o atendimento."),
    ("Internet instavel no setor", "A conexao oscila e interrompe o acesso ao sistema interno."),
    ("Computador nao inicia", "O equipamento liga, mas nao conclui a inicializacao."),
    ("Acesso bloqueado ao sistema", "O usuario nao consegue entrar no sistema utilizado pelo setor."),
    ("Leitor de codigo sem resposta", "O leitor nao reconhece os codigos durante o atendimento."),
    ("Sistema apresenta lentidao", "A tela demora para carregar e algumas operacoes expiram."),
    ("Ponto de rede indisponivel", "A estacao perdeu a comunicacao com a rede local."),
    ("Telefone IP sem audio", "A chamada conecta, mas nao ha audio no aparelho."),
]

STATUS_WEIGHTS = [
    ("open", 25),
    ("in_progress", 30),
    ("resolved", 20),
    ("closed", 20),
    ("reopened", 5),
]

PRIORITIES = ["low", "medium", "high", "critical"]
IMPACTS = ["low", "medium", "high", "critical"]
SLA_HOURS = {"low": 48, "medium": 24, "high": 8, "critical": 2}


def _choose_weighted(rng: random.Random, values: list[tuple[str, int]]) -> str:
    choices = [value for value, _weight in values]
    weights = [weight for _value, weight in values]
    return rng.choices(choices, weights=weights, k=1)[0]


def _name(index: int) -> str:
    first = FIRST_NAMES[index % len(FIRST_NAMES)]
    last = LAST_NAMES[(index * 3) % len(LAST_NAMES)]
    return f"{first} {last}"


def _email(prefix: str, index: int) -> str:
    return f"demo.{prefix}{index:02d}{DEMO_EMAIL_DOMAIN}"


def _ensure_local_sqlite() -> None:
    database_url = normalize_database_url(settings.DATABASE_URL)
    if not database_url.startswith("sqlite:"):
        raise SystemExit(
            "ABORTADO: a carga de demonstracao aceita apenas DATABASE_URL SQLite."
        )

    required_tables = {"users", "tickets", "ticket_events", "comments"}
    missing = [table for table in required_tables if not inspect(engine).has_table(table)]
    if missing:
        raise SystemExit(
            "ABORTADO: o banco local nao esta migrado. Execute 'python -m alembic upgrade head' "
            f"antes de usar o script. Tabelas ausentes: {', '.join(sorted(missing))}."
        )


def _find_demo_users(db):
    return (
        db.query(User)
        .filter(
            or_(
                User.email.like(f"demo.%{DEMO_EMAIL_DOMAIN}"),
                User.email.like(f"demo.%{LEGACY_DEMO_EMAIL_DOMAIN}"),
            )
        )
        .all()
    )


def _find_demo_tickets(db):
    return (
        db.query(Ticket)
        .filter(
            or_(
                Ticket.title.like(f"{DEMO_PREFIX}%"),
                Ticket.title.like(f"{LEGACY_DEMO_PREFIX}%"),
            )
        )
        .all()
    )


def reset_demo_data(db) -> tuple[int, int]:
    demo_users = _find_demo_users(db)
    demo_tickets = _find_demo_tickets(db)
    user_ids = [user.id for user in demo_users]
    ticket_ids = [ticket.id for ticket in demo_tickets]

    notification_ids: list[int] = []
    notification_filters = []
    if ticket_ids:
        notification_filters.append(Notification.ticket_id.in_(ticket_ids))
    if user_ids:
        notification_filters.append(Notification.recipient_id.in_(user_ids))
        notification_filters.append(Notification.actor_id.in_(user_ids))
    if notification_filters:
        notification_ids = [
            notification.id
            for notification in db.query(Notification).filter(or_(*notification_filters)).all()
        ]

    delivery_filters = []
    if notification_ids:
        delivery_filters.append(NotificationDelivery.notification_id.in_(notification_ids))
    if user_ids:
        delivery_filters.append(NotificationDelivery.recipient_id.in_(user_ids))
    if delivery_filters:
        db.query(NotificationDelivery).filter(or_(*delivery_filters)).delete(
            synchronize_session=False
        )
    if notification_filters:
        db.query(Notification).filter(or_(*notification_filters)).delete(
            synchronize_session=False
        )

    if ticket_ids:
        db.query(Comment).filter(Comment.ticket_id.in_(ticket_ids)).delete(
            synchronize_session=False
        )
        db.query(TicketEvent).filter(TicketEvent.ticket_id.in_(ticket_ids)).delete(
            synchronize_session=False
        )
        db.query(Ticket).filter(Ticket.id.in_(ticket_ids)).delete(
            synchronize_session=False
        )

    if user_ids:
        db.query(AccountVerification).filter(AccountVerification.user_id.in_(user_ids)).delete(
            synchronize_session=False
        )
        db.query(TokenBlocklist).filter(TokenBlocklist.user_id.in_(user_ids)).delete(
            synchronize_session=False
        )
        db.query(AuditEvent).filter(AuditEvent.actor_id.in_(user_ids)).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)

    db.commit()
    # O reset pode liberar IDs que serao reutilizados na mesma execucao. A
    # sessao precisa esquecer os objetos removidos antes de criar os novos.
    db.expunge_all()
    return len(demo_users), len(demo_tickets)


def create_demo_users(db, *, technician_count: int, requester_count: int) -> dict[str, list[User] | User]:
    users: list[User] = []
    demo_admin = User(
        name="Administrador Demo",
        email=f"demo.admin{DEMO_EMAIL_DOMAIN}",
        phone="71990000000",
        job_title="Administrador de demonstracao",
        department="Tecnologia",
        unit_name="Unidade de Testes",
        notification_preference="email",
        password_hash=hash_password(DEMO_PASSWORD),
        session_version=1,
        email_verified=True,
        email_verified_at=datetime.now(timezone.utc),
        role="admin",
    )
    db.add(demo_admin)
    users.append(demo_admin)

    for index in range(1, technician_count + 1):
        db.add(
            User(
                name=f"Tecnico Demo {index:02d}",
                email=_email("tecnico", index),
                phone=f"7199000{index:04d}",
                job_title="Tecnico de suporte",
                department="Tecnologia da Informacao",
                unit_name="Central de TI",
                notification_preference="email",
                password_hash=hash_password(DEMO_PASSWORD),
                session_version=1,
                email_verified=True,
                email_verified_at=datetime.now(timezone.utc),
                role="technician",
            )
        )

    for index in range(1, requester_count + 1):
        db.add(
            User(
                name=_name(index),
                email=_email("usuario", index),
                phone=f"7199010{index:04d}",
                job_title="Colaborador da unidade",
                department=SECTORS[index % len(SECTORS)],
                unit_name=UNITS[index % len(UNITS)],
                notification_preference="email",
                password_hash=hash_password(DEMO_PASSWORD),
                session_version=1,
                email_verified=True,
                email_verified_at=datetime.now(timezone.utc),
                role="user",
            )
        )

    db.flush()
    technicians = [user for user in db.query(User).all() if user.role == "technician" and user.email.startswith("demo.")]
    requesters = [user for user in db.query(User).all() if user.role == "user" and user.email.startswith("demo.")]
    return {"admin": demo_admin, "technicians": technicians, "requesters": requesters}


def _add_event(db, *, ticket, actor, event_type, created_at, from_status=None, to_status=None):
    event = TicketEvent(
        ticket_id=ticket.id,
        user_id=actor.id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        created_at=created_at,
    )
    db.add(event)
    return event


def create_demo_tickets(db, *, users: dict, count: int, seed: int) -> int:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    technicians = users["technicians"]
    requesters = users["requesters"]
    created_count = 0

    for index in range(1, count + 1):
        status = _choose_weighted(rng, STATUS_WEIGHTS)
        priority = rng.choice(PRIORITIES)
        impact = rng.choice(IMPACTS)
        category = rng.choice(CATEGORIES)
        sector = rng.choice(SECTORS)
        equipment = rng.choice(EQUIPMENT)
        requester = rng.choice(requesters)
        technician = None
        if status in {"in_progress", "resolved", "closed"}:
            technician = rng.choice(technicians)
        elif status == "reopened" and index % 2 == 0:
            technician = rng.choice(technicians)

        age_days = rng.randint(2, 120) if status in {"resolved", "closed"} else rng.randint(0, 120)
        created_at = now - timedelta(
            days=age_days,
            hours=rng.randint(0, 20),
            minutes=rng.randint(0, 59),
        )
        sla_hours = SLA_HOURS[priority]
        due_at = created_at + timedelta(hours=sla_hours)

        title, description = rng.choice(TICKET_CASES)
        ticket = Ticket(
            title=f"{DEMO_PREFIX}{index:03d} - {title}",
            description=description,
            category=category,
            priority=priority,
            sector=sector,
            equipment=equipment,
            asset_tag=f"DEMO-{index:04d}",
            operational_impact=impact,
            issue_image=None,
            issue_images=[],
            sla_hours=sla_hours,
            due_at=due_at,
            status=status,
            user_id=requester.id,
            technician_id=technician.id if technician else None,
            created_at=created_at,
        )

        if status in {"resolved", "closed"}:
            resolved_at = min(
                created_at + timedelta(hours=rng.randint(1, max(2, sla_hours * 2))),
                now - timedelta(minutes=rng.randint(1, 120)),
            )
            ticket.resolved_at = resolved_at
            ticket.updated_at = resolved_at
        else:
            ticket.updated_at = min(now, created_at + timedelta(hours=rng.randint(1, 8)))

        db.add(ticket)
        db.flush()

        _add_event(
            db,
            ticket=ticket,
            actor=requester,
            event_type="CREATED",
            created_at=created_at,
            to_status="open",
        )
        last_event_at = created_at

        if technician:
            assigned_at = created_at + timedelta(hours=rng.randint(1, 4))
            _add_event(
                db,
                ticket=ticket,
                actor=technician,
                event_type="ASSIGNED",
                created_at=assigned_at,
                from_status="open" if status != "reopened" else "reopened",
                to_status="in_progress" if status != "reopened" else "reopened",
            )
            last_event_at = assigned_at

        if status == "resolved":
            _add_event(
                db,
                ticket=ticket,
                actor=technician or requester,
                event_type="RESOLVED",
                created_at=ticket.resolved_at,
                from_status="in_progress",
                to_status="resolved",
            )
            last_event_at = ticket.resolved_at
        elif status == "closed":
            resolved_at = ticket.resolved_at
            _add_event(
                db,
                ticket=ticket,
                actor=technician or requester,
                event_type="RESOLVED",
                created_at=resolved_at,
                from_status="in_progress",
                to_status="resolved",
            )
            closed_at = min(now - timedelta(minutes=rng.randint(1, 90)), resolved_at + timedelta(hours=2))
            _add_event(
                db,
                ticket=ticket,
                actor=technician or requester,
                event_type="CLOSED",
                created_at=closed_at,
                from_status="resolved",
                to_status="closed",
            )
            last_event_at = closed_at
        elif status == "reopened":
            reopened_at = created_at + timedelta(hours=rng.randint(1, 6))
            _add_event(
                db,
                ticket=ticket,
                actor=requester,
                event_type="REOPENED",
                created_at=reopened_at,
                from_status="closed",
                to_status="reopened",
            )
            last_event_at = reopened_at

        if index % 3 == 0:
            commenter = technician if technician and index % 2 == 0 else requester
            comment_at = last_event_at + timedelta(minutes=15)
            db.add(
                Comment(
                    content=rng.choice(
                        [
                            "Foi realizada uma verificacao inicial do equipamento.",
                            "A equipe confirmou a falha e iniciou o atendimento.",
                            "O setor foi orientado e aguarda nova validacao.",
                        ]
                    ),
                    user_id=commenter.id,
                    ticket_id=ticket.id,
                    created_at=comment_at,
                )
            )
            _add_event(
                db,
                ticket=ticket,
                actor=commenter,
                event_type="COMMENTED",
                created_at=comment_at,
            )

        db.flush()
        created_count += 1

    db.commit()
    return created_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera dados ficticios para testes locais.")
    parser.add_argument("--count", type=int, default=DEFAULT_TICKET_COUNT, help="Quantidade de chamados.")
    parser.add_argument("--technicians", type=int, default=DEFAULT_TECHNICIAN_COUNT, help="Quantidade de tecnicos demo.")
    parser.add_argument("--requesters", type=int, default=DEFAULT_REQUESTER_COUNT, help="Quantidade de usuarios demo.")
    parser.add_argument("--seed", type=int, default=20260921, help="Semente para repetir a mesma distribuicao.")
    parser.add_argument("--reset", action="store_true", help="Remove somente os registros marcados como demo antes de criar novos.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.count < 1 or args.count > 5000:
        raise SystemExit("--count deve ficar entre 1 e 5000.")
    if args.technicians < 1 or args.technicians > 100:
        raise SystemExit("--technicians deve ficar entre 1 e 100.")
    if args.requesters < 1 or args.requesters > 500:
        raise SystemExit("--requesters deve ficar entre 1 e 500.")

    _ensure_local_sqlite()
    db = SessionLocal()
    try:
        existing_users = _find_demo_users(db)
        existing_tickets = _find_demo_tickets(db)
        if (existing_users or existing_tickets) and not args.reset:
            raise SystemExit(
                "Ja existem dados demo neste banco. Use --reset para substituir somente os dados demo."
            )

        if args.reset:
            removed_users, removed_tickets = reset_demo_data(db)
            print(f"Dados demo removidos: {removed_users} usuario(s), {removed_tickets} chamado(s).")

        users = create_demo_users(
            db,
            technician_count=args.technicians,
            requester_count=args.requesters,
        )
        created_tickets = create_demo_tickets(
            db,
            users=users,
            count=args.count,
            seed=args.seed,
        )
    finally:
        db.close()

    print(f"Dados demo criados: {args.technicians + args.requesters + 1} usuario(s), {created_tickets} chamado(s).")
    print(f"Senha local de teste para as contas demo: {DEMO_PASSWORD}")
    print("Admin demo: demo.admin@example.com")
    print("Tecnicos demo: demo.tecnico01@example.com ate demo.tecnico08@example.com")
    print("Os registros possuem prefixo DEMO- e nao contem imagens.")


if __name__ == "__main__":
    main()
