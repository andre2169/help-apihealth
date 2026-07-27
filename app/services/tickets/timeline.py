from app.db.models.ticket_event import TicketEvent
from app.db.models.comment import Comment
from app.schemas.timeline import TimelineItem
from sqlalchemy.orm import Session
from app.db.models.user import User

def get_ticket_timeline(db, ticket_id: int):
    events = (
        db.query(
            TicketEvent.id,
            TicketEvent.event_type.label("action"),
            TicketEvent.from_status,
            TicketEvent.to_status,  
            TicketEvent.created_at,
            User.id.label("user_id"),
            User.name.label("user_name"),
            User.role.label("user_role"),
            User.avatar_image.label("user_avatar_image"),
        )
        .join(User, User.id == TicketEvent.user_id)
        .filter(TicketEvent.ticket_id == ticket_id)
        .all()
    )


    comments = (
        db.query(
            Comment.id,
            Comment.content,
            Comment.created_at,
            User.id.label("user_id"),
            User.name.label("user_name"),
            User.role.label("user_role"),
            User.avatar_image.label("user_avatar_image"),
        )
        .join(User, User.id == Comment.user_id)
        .filter(Comment.ticket_id == ticket_id)
        .all()
    )

    timeline = []

    for event in events:
        timeline.append({
            "type": "event",
            "id": event.id,
            "event_type": event.action,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "created_at": event.created_at,
            "author": {
                "id": event.user_id,
                "name": event.user_name,
                "role": event.user_role,
                "avatar_image": event.user_avatar_image,
            }
        })


    for comment in comments:
        timeline.append({
            "type": "comment",
            "id": comment.id,  
            "content": comment.content,
            "created_at": comment.created_at,
            "author": {
                "id": comment.user_id,
                "name": comment.user_name,
                "role": comment.user_role,
                "avatar_image": comment.user_avatar_image,
            }
        })

    # Ordenar tudo por data
    timeline.sort(key=lambda item: item["created_at"])

    return timeline
