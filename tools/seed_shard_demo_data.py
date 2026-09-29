"""Adiciona dados ficticios de usuarios comuns, chamados, eventos e comentarios.

Execucao apenas manual e interativa. A ferramenta nao apaga nem atualiza dados,
nao envia notificacoes e exige confirmacao explicita antes de gravar.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, load_only, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.security import hash_password
from app.db.models.comment import Comment
from app.db.models.ticket import Ticket
from app.db.models.ticket_event import TicketEvent
from app.db.models.user import User
from app.db.url import normalize_database_url


DEFAULT_USER_COUNT = 30
DEFAULT_TICKET_COUNT = 200
MAX_USER_COUNT = 200
MAX_TICKET_COUNT = 1000
DEMO_EMAIL_DOMAIN = "@example.com"
STATUS_WEIGHTS = {
    "open": 25,
    "in_progress": 30,
    "resolved": 20,
    "closed": 20,
    "reopened": 5,
}
PRIORITIES = ("low", "medium", "high", "critical")
IMPACTS = ("low", "medium", "high", "critical")
SLA_HOURS = {"low": 48, "medium": 24, "high": 8, "critical": 2}
SECTORS = (
    "Recepcao",
    "Enfermagem",
    "Farmacia",
    "Laboratorio",
    "Administrativo",
    "TI",
    "Arquivo",
    "Consultorios",
)
CATEGORIES = ("Rede", "Hardware", "Impressao", "Acesso", "Software", "Infraestrutura")
EQUIPMENT = ("Computador", "Impressora", "Switch", "Roteador", "Leitor", "Sistema interno")
UNITS = (
    "UBS Centro",
    "UPA Municipal",
    "Hospital Regional",
    "Laboratorio Municipal",
    "Policlinica",
)
CASES = (
    ("Impressora sem resposta", "A impressora do setor parou de responder durante o expediente."),
    ("Conexao instavel", "A conexao oscila e interrompe o acesso aos sistemas internos."),
    ("Computador nao inicia", "O equipamento liga, mas nao conclui a inicializacao."),
    ("Acesso ao sistema bloqueado", "O colaborador nao consegue acessar o sistema do setor."),
    ("Leitor sem resposta", "O leitor nao reconhece os codigos durante o atendimento."),
    ("Sistema lento", "A tela demora para carregar e algumas operacoes expiram."),
    ("Ponto de rede indisponivel", "A estacao perdeu comunicacao com a rede local."),
    ("Telefone IP sem audio", "A chamada conecta, mas nao ha audio no aparelho."),
)
COMMENT_TEXTS = (
    "Foi realizada uma verificacao inicial do equipamento.",
    "A equipe confirmou a falha e iniciou a analise.",
    "O setor foi orientado e aguarda nova validacao.",
)
FIRST_NAMES = (
    "Ana", "Bruno", "Camila", "Daniel", "Eduarda", "Felipe", "Gabriela", "Henrique",
    "Isabela", "Joao", "Larissa", "Marcos", "Natalia", "Otavio", "Paula", "Rafael",
    "Sabrina", "Thiago", "Vanessa", "William",
)
LAST_NAMES = (
    "Almeida", "Barbosa", "Cardoso", "Dias", "Ferreira", "Gomes", "Lima", "Mendes",
    "Nunes", "Oliveira", "Pereira", "Ramos", "Santos", "Silva", "Souza",
)


def _validate_run_id(run_id: str) -> str:
    normalized = run_id.strip().lower()
    if not re.fullmatch(r"[a-z0-9-]{4,20}", normalized):
        raise ValueError("O identificador da carga deve ter de 4 a 20 letras, numeros ou hifens.")
    return normalized


def _weighted_statuses(count: int, rng: random.Random) -> list[str]:
    quotas = {status: count * weight // 100 for status, weight in STATUS_WEIGHTS.items()}
    remaining = count - sum(quotas.values())
    remainder_order = sorted(
        STATUS_WEIGHTS,
        key=lambda status: (count * STATUS_WEIGHTS[status]) % 100,
        reverse=True,
    )
    for status in remainder_order[:remaining]:
        quotas[status] += 1

    statuses = [status for status, amount in quotas.items() for _ in range(amount)]
    rng.shuffle(statuses)
    return statuses


def ensure_run_is_unused(db: Session, run_id: str) -> None:
    email_prefix = f"demo.shard.{run_id}.%"
    ticket_prefix = f"DEMO-SHARD-{run_id.upper()}-%"
    existing_user = db.query(User.id).filter(User.email.like(email_prefix)).first()
    existing_ticket = db.query(Ticket.id).filter(Ticket.title.like(ticket_prefix)).first()
    if existing_user or existing_ticket:
        raise ValueError(
            "Ja existem registros desta carga. Escolha outro identificador para evitar duplicacao."
        )


def load_existing_event_actors(db: Session) -> tuple[list[User], list[User]]:
    user_event_fields = load_only(User.id, User.role, User.is_active)
    technicians = (
        db.query(User)
        .options(user_event_fields)
        .filter(User.role == "technician", User.is_active.is_(True))
        .all()
    )
    administrators = (
        db.query(User)
        .options(user_event_fields)
        .filter(User.role == "admin", User.is_active.is_(True))
        .all()
    )
    return technicians, administrators


def _add_event(
    db: Session,
    *,
    ticket: Ticket,
    actor: User,
    event_type: str,
    created_at: datetime,
    from_status: str | None = None,
    to_status: str | None = None,
) -> None:
    db.add(
        TicketEvent(
            ticket_id=ticket.id,
            user_id=actor.id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            created_at=created_at,
        )
    )


def create_demo_dataset(
    db: Session,
    *,
    user_count: int = DEFAULT_USER_COUNT,
    ticket_count: int = DEFAULT_TICKET_COUNT,
    run_id: str,
    seed: int | None = None,
    technicians: list[User] | None = None,
    administrators: list[User] | None = None,
) -> dict[str, int]:
    """Insere somente novos registros; o chamador controla a transacao."""
    run_id = _validate_run_id(run_id)
    if not 1 <= user_count <= MAX_USER_COUNT:
        raise ValueError(f"A quantidade de usuarios deve ficar entre 1 e {MAX_USER_COUNT}.")
    if not 1 <= ticket_count <= MAX_TICKET_COUNT:
        raise ValueError(f"A quantidade de chamados deve ficar entre 1 e {MAX_TICKET_COUNT}.")
    ensure_run_is_unused(db, run_id)

    rng = random.Random(seed if seed is not None else secrets.randbits(64))
    now = datetime.now(timezone.utc)
    requesters: list[User] = []

    for index in range(1, user_count + 1):
        first = FIRST_NAMES[(index - 1) % len(FIRST_NAMES)]
        last = LAST_NAMES[((index - 1) * 3) % len(LAST_NAMES)]
        requester = User(
            name=f"{first} {last} Demo {run_id[:4].upper()}",
            email=f"demo.shard.{run_id}.user{index:03d}{DEMO_EMAIL_DOMAIN}",
            phone=f"7198{index:07d}"[:13],
            job_title="Colaborador da unidade",
            department=SECTORS[(index - 1) % len(SECTORS)],
            unit_name=UNITS[(index - 1) % len(UNITS)],
            notification_preference="email",
            password_hash=hash_password(secrets.token_urlsafe(32)),
            session_version=1,
            email_verified=True,
            email_verified_at=now,
            role="user",
            is_active=True,
        )
        db.add(requester)
        requesters.append(requester)

    db.flush()
    statuses = _weighted_statuses(ticket_count, rng)
    available_technicians = [user for user in (technicians or []) if user.role == "technician"]
    available_admins = [user for user in (administrators or []) if user.role == "admin"]
    comments_created = 0

    for index, status in enumerate(statuses, start=1):
        requester = rng.choice(requesters)
        technician = rng.choice(available_technicians) if available_technicians else None
        event_actor = technician or (rng.choice(available_admins) if available_admins else requester)
        priority = rng.choice(PRIORITIES)
        impact = rng.choice(IMPACTS)
        sla_hours = SLA_HOURS[priority]
        age_days = rng.randint(2, 120) if status in {"resolved", "closed", "reopened"} else rng.randint(0, 120)
        created_at = now - timedelta(
            days=age_days,
            hours=rng.randint(0, 20),
            minutes=rng.randint(0, 59),
        )
        title, description = rng.choice(CASES)
        ticket = Ticket(
            title=f"DEMO-SHARD-{run_id.upper()}-{index:04d} | {title}",
            description=f"[DADO FICTICIO PARA TESTE] {description}",
            category=rng.choice(CATEGORIES),
            priority=priority,
            sector=rng.choice(SECTORS),
            equipment=rng.choice(EQUIPMENT),
            asset_tag=f"D-{run_id[:8].upper()}-{index:04d}",
            operational_impact=impact,
            issue_image=None,
            issue_images=None,
            sla_hours=sla_hours,
            due_at=created_at + timedelta(hours=sla_hours),
            status=status,
            user_id=requester.id,
            technician_id=technician.id if technician else None,
            created_at=created_at,
        )

        if status in {"resolved", "closed"}:
            ticket.resolved_at = min(
                created_at + timedelta(hours=rng.randint(1, max(2, sla_hours * 2))),
                now - timedelta(minutes=1),
            )
            ticket.updated_at = ticket.resolved_at
        elif status == "reopened":
            ticket.resolved_at = None
            ticket.updated_at = min(now, created_at + timedelta(hours=8))
        else:
            ticket.updated_at = min(now, created_at + timedelta(hours=rng.randint(0, 8)))

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

        if status in {"in_progress", "resolved", "closed", "reopened"}:
            assigned_at = created_at + timedelta(hours=1)
            _add_event(
                db,
                ticket=ticket,
                actor=event_actor,
                event_type="ASSIGNED",
                created_at=assigned_at,
                from_status="open",
                to_status="in_progress",
            )
            last_event_at = assigned_at

        if status in {"resolved", "closed", "reopened"}:
            resolved_at = ticket.resolved_at or min(
                created_at + timedelta(hours=max(2, sla_hours)),
                now - timedelta(minutes=2),
            )
            _add_event(
                db,
                ticket=ticket,
                actor=event_actor,
                event_type="RESOLVED",
                created_at=resolved_at,
                from_status="in_progress",
                to_status="resolved",
            )
            last_event_at = resolved_at

        if status in {"closed", "reopened"}:
            closed_at = min(now - timedelta(minutes=1), last_event_at + timedelta(minutes=30))
            _add_event(
                db,
                ticket=ticket,
                actor=requester,
                event_type="CLOSED",
                created_at=closed_at,
                from_status="resolved",
                to_status="closed",
            )
            last_event_at = closed_at

        if status == "reopened":
            reopened_at = min(now, last_event_at + timedelta(minutes=30))
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
            comment_at = min(now, last_event_at + timedelta(minutes=15))
            db.add(
                Comment(
                    content=rng.choice(COMMENT_TEXTS),
                    user_id=requester.id,
                    ticket_id=ticket.id,
                    created_at=comment_at,
                )
            )
            _add_event(
                db,
                ticket=ticket,
                actor=requester,
                event_type="COMMENTED",
                created_at=comment_at,
            )
            comments_created += 1

    db.flush()
    return {
        "users": user_count,
        "tickets": ticket_count,
        "events": db.query(TicketEvent.id)
        .join(Ticket, Ticket.id == TicketEvent.ticket_id)
        .filter(Ticket.title.like(f"DEMO-SHARD-{run_id.upper()}-%"))
        .count(),
        "comments": comments_created,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Adiciona dados ficticios a um PostgreSQL remoto, sem apagar dados existentes."
    )
    parser.add_argument("--users", type=int, default=DEFAULT_USER_COUNT)
    parser.add_argument("--tickets", type=int, default=DEFAULT_TICKET_COUNT)
    parser.add_argument("--run-id", help="Identificador unico (4-20 caracteres) para esta carga.")
    parser.add_argument("--seed", type=int, help="Semente opcional para repetir a distribuicao.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Grava os dados. Sem esta opcao, a execucao e apenas uma simulacao.",
    )
    return parser.parse_args()


def _get_remote_database_url() -> tuple[str, str]:
    raw_url = os.environ.pop("HELPWEB_DEMO_DATABASE_URL", "").strip()
    if not raw_url:
        raise SystemExit(
            "URL nao informada. No PowerShell, carregue-a com Read-Host -AsSecureString "
            "e defina temporariamente HELPWEB_DEMO_DATABASE_URL antes de executar."
        )

    normalized_url = normalize_database_url(raw_url)
    parsed = make_url(normalized_url)
    if not parsed.drivername.startswith("postgresql") or not parsed.host:
        raise SystemExit("ABORTADO: esta ferramenta aceita somente PostgreSQL remoto.")
    if parsed.host.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("ABORTADO: informe o PostgreSQL remoto da hospedagem.")
    return normalized_url, parsed.host


def main() -> None:
    args = _parse_args()
    if not 1 <= args.users <= MAX_USER_COUNT:
        raise SystemExit(f"--users deve ficar entre 1 e {MAX_USER_COUNT}.")
    if not 1 <= args.tickets <= MAX_TICKET_COUNT:
        raise SystemExit(f"--tickets deve ficar entre 1 e {MAX_TICKET_COUNT}.")

    run_id = _validate_run_id(args.run_id or secrets.token_hex(4))
    database_url, host = _get_remote_database_url()
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
        pool_timeout=15,
        connect_args={"connect_timeout": 10},
    )
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)

    try:
        missing_tables = [
            name
            for name in ("users", "tickets", "ticket_events", "comments")
            if not inspect(engine).has_table(name)
        ]
        if missing_tables:
            raise SystemExit(
                "ABORTADO: faltam tabelas no banco. Confira se as migracoes estao aplicadas."
            )

        with SessionFactory() as db:
            ensure_run_is_unused(db, run_id)
            db.rollback()
            print(f"Destino PostgreSQL: {host}")
            print(f"Marcador exclusivo: DEMO-SHARD-{run_id.upper()}")
            print(
                f"Previsao: {args.users} usuarios comuns, {args.tickets} chamados, "
                f"eventos de historico e aproximadamente {args.tickets // 3} comentarios."
            )
            print("Nenhuma senha sera exibida; nao havera envio de emails ou notificacoes.")

            if not args.apply:
                print("Simulacao concluida: nada foi gravado. Use --apply para confirmar a inclusao.")
                return

            confirmation = input(f"Para gravar, digite ADICIONAR DEMO EM {host}: ").strip()
            if confirmation != f"ADICIONAR DEMO EM {host}":
                print("Confirmacao diferente; nada foi gravado.")
                return

            with db.begin():
                ensure_run_is_unused(db, run_id)
                technicians, administrators = load_existing_event_actors(db)
                counts = create_demo_dataset(
                    db,
                    user_count=args.users,
                    ticket_count=args.tickets,
                    run_id=run_id,
                    seed=args.seed,
                    technicians=technicians,
                    administrators=administrators,
                )

            print(
                "Inclusao concluida: "
                f"{counts['users']} usuarios comuns, {counts['tickets']} chamados, "
                f"{counts['events']} eventos e {counts['comments']} comentarios."
            )
            print("Todos os registros podem ser identificados pelo marcador DEMO-SHARD-" + run_id.upper() + ".")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
