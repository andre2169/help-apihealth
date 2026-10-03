from sqlalchemy.orm import declarative_base

Base = declarative_base()

import app.db.models
from app.db.models.user import User
from app.db.models.ticket import Ticket
from app.db.models.comment import Comment
from app.db.models.ticket_event import TicketEvent
from app.db.models.account_verification import AccountVerification
from app.db.models.token_blocklist import TokenBlocklist
from app.db.models.audit_event import AuditEvent
from app.db.models.notification import Notification
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.mfa_recovery_code import MFARecoveryCode
from app.db.models.maintenance_notice import MaintenanceNotice
from app.db.models.maintenance_notice_read import MaintenanceNoticeRead
