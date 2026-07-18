from app.core.exceptions import TicketPermissionDenied

def can_view_ticket_timeline(*, user, ticket):
    if user.role in ["admin", "technician"]:
        return

    if user.role == "user" and ticket.user_id == user.id:
        return

    raise TicketPermissionDenied(
        "Você não tem permissão para ver a timeline deste ticket"
    )
