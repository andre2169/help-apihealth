from app.db.session import SessionLocal
from app.db.models.user import User
from app.db.models.ticket import Ticket
from app.core.events import create_ticket_event
from datetime import datetime, timedelta, timezone


def seed_tickets():
    db = SessionLocal()

    try:
        user8 = db.query(User).filter(User.email == "user8@test.com").first()
        user9 = db.query(User).filter(User.email == "user9@test.com").first()
        user10 = db.query(User).filter(User.email == "user10@test.com").first()
        user11 = db.query(User).filter(User.email == "user11@test.com").first()
        #tech2 = db.query(User).filter(User.email == "tech2@test.com").first()

        if not user8 or not user9 or not user10 or not user11:
            print("Usuários necessários não encontrados. Rode primeiro: python -m scripts.seed_users")
            return

        tickets_data = [
            {
                "title": "Impressora da UTI não imprime prescrições",
                "description": "A impressora da UTI parou de imprimir documentos internos e prescrições. Não incluir dados de pacientes no chamado.",
                "category": "Impressão",
                "priority": "critical",
                "sector": "UTI",
                "equipment": "Impressora térmica",
                "asset_tag": "PAT-UTI-0042",
                "operational_impact": "critical",
                "sla_hours": 2,
                "user": user8,
                "technician": None,
                "status": "open",
            },
            {
                "title": "Wi-Fi instável no pronto atendimento",
                "description": "Profissionais relatam queda de conexão nos notebooks usados para acesso aos sistemas internos.",
                "category": "Rede",
                "priority": "high",
                "sector": "Pronto Atendimento",
                "equipment": "Access point",
                "asset_tag": "AP-PA-0007",
                "operational_impact": "high",
                "sla_hours": 8,
                "user": user9,
                "technician": None,
                "status": "open",
            },
            {
                "title": "Leitor de código de barras não reconhece etiquetas",
                "description": "O leitor do laboratório não reconhece etiquetas internas, atrasando o fluxo de registro de amostras.",
                "category": "Hardware",
                "priority": "medium",
                "sector": "Laboratório",
                "equipment": "Leitor de código de barras",
                "asset_tag": "LAB-BC-0013",
                "operational_impact": "medium",
                "sla_hours": 24,
                "user": user10,
                "technician": None,
                "status": "open",
            },
            {
                "title": "Computador da recepção sem acesso ao sistema",
                "description": "A estação da recepção abre a rede, mas não acessa o sistema administrativo interno.",
                "category": "Software hospitalar",
                "priority": "high",
                "sector": "Recepção",
                "equipment": "Estação de trabalho",
                "asset_tag": "REC-PC-0021",
                "operational_impact": "high",
                "sla_hours": 8,
                "user": user11,
                "technician": None,
                "status": "open",
            },
        ]

        for data in tickets_data:
            existing = db.query(Ticket).filter(
                Ticket.title == data["title"],
                Ticket.user_id == data["user"].id,
            ).first()

            if existing:
                print(f"Ticket já existe: {data['title']}")
                continue

            ticket = Ticket(
                title=data["title"],
                description=data["description"],
                category=data["category"],
                priority=data["priority"],
                sector=data["sector"],
                equipment=data["equipment"],
                asset_tag=data["asset_tag"],
                operational_impact=data["operational_impact"],
                sla_hours=data["sla_hours"],
                due_at=datetime.now(timezone.utc) + timedelta(hours=data["sla_hours"]),
                status=data["status"],
                user_id=data["user"].id,
                technician_id=data["technician"].id if data["technician"] else None,
            )

            db.add(ticket)
            db.commit()
            db.refresh(ticket)

            # CREATED
            create_ticket_event(
                db=db,
                ticket_id=ticket.id,
                user_id=data["user"].id,
                event_type="CREATED",
                to_status="open",
            )

            # ASSIGNED
            if data["status"] in ["in_progress", "resolved", "closed"] and data["technician"]:
                create_ticket_event(
                    db=db,
                    ticket_id=ticket.id,
                    user_id=data["technician"].id,
                    event_type="ASSIGNED",
                    from_status="open",
                    to_status="in_progress",
                )

            # RESOLVED
            if data["status"] in ["resolved", "closed"] and data["technician"]:
                create_ticket_event(
                    db=db,
                    ticket_id=ticket.id,
                    user_id=data["technician"].id,
                    event_type="RESOLVED",
                    from_status="in_progress",
                    to_status="resolved",
                )

            # CLOSED
            if data["status"] == "closed":
                create_ticket_event(
                    db=db,
                    ticket_id=ticket.id,
                    user_id=data["user"].id,
                    event_type="CLOSED",
                    from_status="resolved",
                    to_status="closed",
                )

            db.commit()
            print(f"Ticket criado: {ticket.title}")

        print("Seed de tickets concluído!")

    finally:
        db.close()


if __name__ == "__main__":
    seed_tickets()
