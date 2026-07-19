import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.account_verification import AccountVerification
from app.db.models.user import User
from app.services.email_service import send_email


logger = logging.getLogger(__name__)

PURPOSE_PASSWORD_CHANGE = "password_change"
PURPOSE_EMAIL_CHANGE = "email_change"
PURPOSE_PASSWORD_RECOVERY = "password_recovery"
MAX_VERIFICATION_ATTEMPTS = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(expires_at: datetime) -> bool:
    current_time = _now()
    if expires_at.tzinfo is None:
        current_time = current_time.replace(tzinfo=None)
    return expires_at <= current_time


def _normalize_target(value: str | None) -> str | None:
    return value.strip().lower() if value else None


def _seconds_since(created_at: datetime, now: datetime) -> int:
    if created_at.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    elif created_at.tzinfo is not None and now.tzinfo is None:
        created_at = created_at.replace(tzinfo=None)

    return max(0, int((now - created_at).total_seconds()))


def _format_wait(seconds: int) -> str:
    minutes = max(1, (seconds + 59) // 60)
    return f"{minutes} minuto" if minutes == 1 else f"{minutes} minutos"


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_code(code: str) -> str:
    """
    Usa HMAC com a SECRET_KEY da aplicação para evitar salvar o código puro.
    Mesmo se alguém acessar o banco, o código temporário não fica legível.
    """
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_password_change_target(new_password: str) -> str:
    """
    Vincula o código à nova senha escolhida sem salvar a senha em texto puro.

    Na confirmação, a API calcula esse mesmo alvo e só aceita o código se ele
    tiver sido gerado para aquela nova senha. Isso evita pedir a senha atual
    duas vezes e reduz erro de preenchimento/autofill no navegador.
    """
    return f"password:{_hash_code(f'password-change:{new_password}')}"


def _message_for_code(*, user: User, code: str, purpose: str) -> tuple[str, str]:
    if purpose == PURPOSE_EMAIL_CHANGE:
        subject = "Confirme a alteração de email - HelpWeb Health"
        action = "alterar o email da sua conta"
    elif purpose == PURPOSE_PASSWORD_RECOVERY:
        subject = "Recupere sua senha - HelpWeb Health"
        action = "recuperar o acesso à sua conta"
    else:
        subject = "Confirme a alteração de senha - HelpWeb Health"
        action = "alterar a senha da sua conta"

    body = (
        f"Olá, {user.name}.\n\n"
        f"Seu código para {action} é: {code}\n\n"
        f"Esse código expira em {settings.EMAIL_CODE_EXPIRE_MINUTES} minutos. "
        "Se você não solicitou essa alteração, ignore esta mensagem e avise o suporte.\n\n"
        "HelpWeb Health"
    )
    return subject, body


def create_account_verification(
    *,
    db: Session,
    user: User,
    purpose: str,
    recipient_email: str,
    target_value: str | None = None,
) -> bool:
    """
    Cria um código temporário e invalida códigos anteriores do mesmo fluxo.

    Retorna True quando o email foi enviado por SMTP. Se SMTP não estiver
    configurado, retorna False. O código só aparece em log quando
    ALLOW_LOG_VERIFICATION_CODES=true, opção voltada a teste local.
    """
    normalized_target = _normalize_target(target_value)
    now = _now()
    cooldown = max(0, settings.VERIFICATION_RESEND_COOLDOWN_SECONDS)

    active_code = (
        db.query(AccountVerification)
        .filter(
            AccountVerification.user_id == user.id,
            AccountVerification.purpose == purpose,
            AccountVerification.target_value == normalized_target,
            AccountVerification.used_at.is_(None),
        )
        .order_by(AccountVerification.created_at.desc())
        .first()
    )

    if active_code and not _is_expired(active_code.expires_at):
        retry_after = cooldown - _seconds_since(active_code.created_at or now, now)
        if retry_after > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Aguarde {_format_wait(retry_after)} para reenviar o código.",
                headers={"Retry-After": str(retry_after)},
            )

    (
        db.query(AccountVerification)
        .filter(
            AccountVerification.user_id == user.id,
            AccountVerification.purpose == purpose,
            AccountVerification.used_at.is_(None),
        )
        .update({AccountVerification.used_at: now}, synchronize_session=False)
    )

    code = _generate_code()
    verification = AccountVerification(
        user_id=user.id,
        purpose=purpose,
        target_value=normalized_target,
        code_hash=_hash_code(code),
        expires_at=now + timedelta(minutes=settings.EMAIL_CODE_EXPIRE_MINUTES),
    )

    db.add(verification)
    db.commit()

    subject, body = _message_for_code(user=user, code=code, purpose=purpose)
    try:
        email_sent = send_email(
            to_email=recipient_email,
            subject=subject,
            body=body,
        )
    except Exception:
        logger.exception("Falha ao enviar codigo de verificacao por email")
        email_sent = False

    if not email_sent and settings.ALLOW_LOG_VERIFICATION_CODES:
        logger.warning(
            "Codigo de verificacao gerado em modo local | user_id=%s | purpose=%s | code=%s",
            user.id,
            purpose,
            code,
        )
    elif not email_sent:
        logger.warning(
            "Codigo de verificacao gerado mas nao exibido em log | user_id=%s | purpose=%s",
            user.id,
            purpose,
        )

    return email_sent


def consume_account_verification(
    *,
    db: Session,
    user: User,
    purpose: str,
    code: str,
    target_value: str | None = None,
) -> AccountVerification:
    normalized_target = _normalize_target(target_value)
    verification = (
        db.query(AccountVerification)
        .filter(
            AccountVerification.user_id == user.id,
            AccountVerification.purpose == purpose,
            AccountVerification.target_value == normalized_target,
            AccountVerification.used_at.is_(None),
        )
        .order_by(AccountVerification.created_at.desc())
        .first()
    )

    if not verification or _is_expired(verification.expires_at):
        logger.warning(
            "Codigo de verificacao ausente ou expirado | user_id=%s | purpose=%s",
            user.id,
            purpose,
        )
        raise HTTPException(status_code=400, detail="Código inválido ou expirado")

    if verification.attempts >= MAX_VERIFICATION_ATTEMPTS:
        logger.warning(
            "Codigo de verificacao bloqueado por tentativas | user_id=%s | purpose=%s | attempts=%s",
            user.id,
            purpose,
            verification.attempts,
        )
        raise HTTPException(status_code=400, detail="Código bloqueado por muitas tentativas")

    if not hmac.compare_digest(verification.code_hash, _hash_code(code)):
        verification.attempts += 1
        db.commit()
        logger.warning(
            "Codigo de verificacao invalido | user_id=%s | purpose=%s | attempts=%s",
            user.id,
            purpose,
            verification.attempts,
        )
        raise HTTPException(status_code=400, detail="Código inválido")

    verification.used_at = _now()
    return verification
