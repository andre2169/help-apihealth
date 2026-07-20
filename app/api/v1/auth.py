import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas.auth import AccountRecoveryConfirm, AccountRecoveryRequest, LoginRequest, LoginResponse
from app.schemas.user import (
    EmailChangeConfirm,
    EmailChangeRequest,
    EmailVerificationConfirm,
    PasswordChange,
    PasswordChangeConfirm,
    UserProfileUpdate,
    UserResponse,
)
from app.db.models.user import User
from app.core.config import settings
from app.core.auth import decode_access_token
from app.core.request_context import get_client_ip, mask_email
from app.core.security import hash_password, verify_password

from app.services.auth_service import login_service
from app.core.exceptions import InvalidCredentials
from app.core.dependencies import extract_auth_token, get_current_user, security
from app.services.account_verification_service import (
    PURPOSE_EMAIL_CHANGE,
    PURPOSE_EMAIL_VERIFICATION,
    PURPOSE_PASSWORD_CHANGE,
    PURPOSE_PASSWORD_RECOVERY,
    build_password_change_target,
    consume_account_verification,
    create_account_verification,
)
from app.services.token_service import revoke_token
from app.services.audit_service import record_audit_event

from app.services.rate_limit_service import (
    check_login_rate_limit,
    consume_action_rate_limit,
    register_failed_login,
    clear_failed_login,
) 

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/auth",
    tags=["Auth"],
)


def _http_error(exc: Exception, email: str | None = None):
    if isinstance(exc, InvalidCredentials):
        logger.warning(
            "Tentativa de login invalida | email=%s",
            mask_email(email),
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha inválidos",
        )
    
    raise exc


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        httponly=True,
    )


def _bump_session_version(user: User) -> None:
    user.session_version = (user.session_version or 1) + 1


def _wait_account_recovery_floor(started_at: float) -> None:
    remaining = settings.ACCOUNT_RECOVERY_MIN_RESPONSE_SECONDS - (time.monotonic() - started_at)
    if remaining > 0:
        time.sleep(remaining)


def _check_account_recovery_rate_limit(*, ip: str, email: str) -> None:
    window = settings.ACCOUNT_RECOVERY_WINDOW_SECONDS
    email_allowed = consume_action_rate_limit(
        action="password_recovery_email",
        key=email,
        max_requests=settings.ACCOUNT_RECOVERY_MAX_REQUESTS_PER_EMAIL,
        window_seconds=window,
    )
    ip_allowed = consume_action_rate_limit(
        action="password_recovery_ip",
        key=ip,
        max_requests=settings.ACCOUNT_RECOVERY_MAX_REQUESTS_PER_IP,
        window_seconds=window,
    )
    if not email_allowed or not ip_allowed:
        raise HTTPException(
            status_code=429,
            detail="Muitas solicitações de recuperação. Aguarde alguns minutos.",
            headers={"Retry-After": str(window)},
        )


def _verification_response(email_sent: bool):
    base_response = {
        "status": "verification_required",
        "expires_in_minutes": settings.EMAIL_CODE_EXPIRE_MINUTES,
        "resend_after_seconds": settings.VERIFICATION_RESEND_COOLDOWN_SECONDS,
    }

    if email_sent:
        return {
            **base_response,
            "delivery": "email",
            "message": "Código enviado para o email informado.",
        }

    return {
        **base_response,
        "delivery": "log",
        "message": "SMTP não configurado. Use o código exibido nos logs da API.",
    }


def _account_recovery_response(email_sent: bool = True):
    return {
        "status": "verification_required",
        "delivery": "email" if email_sent else "log",
        "expires_in_minutes": settings.EMAIL_CODE_EXPIRE_MINUTES,
        "resend_after_seconds": settings.VERIFICATION_RESEND_COOLDOWN_SECONDS,
        "message": (
            "Se houver uma conta com esse email, enviaremos um código de recuperação."
        ),
    }


@router.post(
    "/login",
    response_model=LoginResponse,
)
def login(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: Session = Depends(get_db),
):
    ip = get_client_ip(request)

    if not check_login_rate_limit(ip, data.email):

        logger.warning(
            "Login bloqueado por rate limit | ip=%s | email=%s",
            ip,
            mask_email(data.email),
        )

        raise HTTPException(
            status_code=429,
            detail="Muitas tentativas de login. Aguarde alguns minutos.",
        )

    try:
        logger.info(
            "Tentativa de login | ip=%s | email=%s",
            ip,
            mask_email(data.email),
        )

        token_response = login_service(
            db=db,
            email=data.email,
            password=data.password,
        )
        _set_auth_cookie(response, token_response["access_token"])

        # Login deu certo
        # Zera histórico de falhas
        clear_failed_login(ip, data.email)

        logger.info(
            "Login realizado com sucesso | ip=%s | email=%s",
            ip,
            mask_email(data.email),
        )

        return {"status": "ok", "token_type": "cookie"}

    except Exception as e:

        # Login inválido
        if isinstance(e, InvalidCredentials):

            register_failed_login(
                ip,
                data.email,
            )

        _http_error(
            e,
            email=data.email,
        )


@router.post("/password/recovery/request")
def request_account_recovery(
    request: Request,
    data: AccountRecoveryRequest,
    db: Session = Depends(get_db),
):
    started_at = time.monotonic()
    email = _normalize_email(str(data.email))
    ip = get_client_ip(request)
    response_payload = _account_recovery_response()
    pending_error: HTTPException | None = None

    try:
        _check_account_recovery_rate_limit(ip=ip, email=email)
        user = db.query(User).filter(User.email == email).first()

        if not user:
            logger.info(
                "Recuperacao de conta solicitada para email nao cadastrado | ip=%s | email=%s",
                ip,
                mask_email(email),
            )
        else:
            email_sent = create_account_verification(
                db=db,
                user=user,
                purpose=PURPOSE_PASSWORD_RECOVERY,
                recipient_email=user.email,
                target_value=build_password_change_target(data.new_password),
            )
            response_payload = _account_recovery_response(email_sent)

            logger.info(
                "Codigo de recuperacao de conta solicitado | ip=%s | user_id=%s | email=%s",
                ip,
                user.id,
                mask_email(user.email),
            )
    except HTTPException as exc:
        pending_error = exc

    _wait_account_recovery_floor(started_at)
    if pending_error:
        raise pending_error
    return response_payload


@router.post("/password/recovery/confirm")
def confirm_account_recovery(
    request: Request,
    data: AccountRecoveryConfirm,
    db: Session = Depends(get_db),
):
    email = _normalize_email(str(data.email))
    ip = get_client_ip(request)
    user = db.query(User).filter(User.email == email).first()

    if not user:
        logger.warning(
            "Confirmacao de recuperacao para email nao cadastrado | ip=%s | email=%s",
            ip,
            mask_email(email),
        )
        raise HTTPException(status_code=400, detail="Código inválido ou expirado")

    consume_account_verification(
        db=db,
        user=user,
        purpose=PURPOSE_PASSWORD_RECOVERY,
        target_value=build_password_change_target(data.new_password),
        code=data.code,
    )

    user.password_hash = hash_password(data.new_password)
    _bump_session_version(user)
    record_audit_event(
        db,
        actor_id=user.id,
        action="auth.password_recovered",
        target_type="user",
        target_id=user.id,
        ip_address=ip,
    )
    db.commit()

    logger.info(
        "Senha redefinida por recuperacao de conta | ip=%s | user_id=%s",
        ip,
        user.id,
    )
    return {"status": "ok", "message": "Senha redefinida com sucesso."}


@router.get("/me", response_model=UserResponse)
def read_me(
    current_user: User = Depends(get_current_user),
):
    logger.info(
        "Consulta ao usuario autenticado | user_id=%s | role=%s",
        current_user.id,
        current_user.role,
    )

    return current_user


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
):
    token = extract_auth_token(request, credentials)
    user_id = None
    if token:
        payload = decode_access_token(token)
        if payload and payload.get("sub"):
            try:
                user_id = int(payload["sub"])
            except (TypeError, ValueError):
                user_id = None

    revoked = revoke_token(
        db=db,
        token=token or "",
        user_id=user_id,
    )
    _clear_auth_cookie(response)
    logger.info(
        "Logout solicitado | user_id=%s | revoked=%s",
        user_id,
        revoked,
    )
    return {"status": "ok"}


@router.post("/me/email-verification/request")
def request_my_email_verification(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.email_verified:
        return {"status": "ok", "message": "Email já confirmado."}

    email_sent = create_account_verification(
        db=db,
        user=current_user,
        purpose=PURPOSE_EMAIL_VERIFICATION,
        recipient_email=current_user.email,
        target_value=current_user.email,
    )
    logger.info("Codigo de confirmacao de cadastro solicitado | user_id=%s", current_user.id)
    return _verification_response(email_sent)


@router.post("/me/email-verification/confirm", response_model=UserResponse)
def confirm_my_email_verification(
    data: EmailVerificationConfirm,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_email = _normalize_email(current_user.email)
    consume_account_verification(
        db=db,
        user=current_user,
        purpose=PURPOSE_EMAIL_VERIFICATION,
        target_value=current_email,
        code=data.code,
    )
    current_user.email_verified = True
    current_user.email_verified_at = datetime.now(timezone.utc)
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="auth.email_verified",
        target_type="user",
        target_id=current_user.id,
    )
    db.commit()
    db.refresh(current_user)
    logger.info("Email confirmado | user_id=%s", current_user.id)
    return current_user


@router.patch("/me", response_model=UserResponse)
def update_me(
    data: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Dados não sensíveis podem ser atualizados direto pelo perfil.
    # Email e senha usam endpoints próprios com código de confirmação.
    changed_fields: list[str] = []

    if data.name:
        current_user.name = data.name
        changed_fields.append("name")

    if data.phone is not None:
        current_user.phone = data.phone or None
        changed_fields.append("phone")

    if data.job_title is not None:
        current_user.job_title = data.job_title or None
        changed_fields.append("job_title")

    if data.department is not None:
        current_user.department = data.department or None
        changed_fields.append("department")

    if data.unit_name is not None:
        current_user.unit_name = data.unit_name or None
        changed_fields.append("unit_name")

    if data.notification_preference is not None:
        current_user.notification_preference = data.notification_preference or "email"
        changed_fields.append("notification_preference")

    if data.avatar_image is not None:
        current_user.avatar_image = data.avatar_image or None
        changed_fields.append("avatar_image")

    if changed_fields:
        record_audit_event(
            db,
            actor_id=current_user.id,
            action="user.profile_updated",
            target_type="user",
            target_id=current_user.id,
            details={"changed_fields": changed_fields},
        )

    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/password/request")
def request_my_password_change(
    data: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")

    email_sent = create_account_verification(
        db=db,
        user=current_user,
        purpose=PURPOSE_PASSWORD_CHANGE,
        recipient_email=current_user.email,
        target_value=build_password_change_target(data.new_password),
    )

    logger.info(
        "Codigo de troca de senha solicitado | user_id=%s",
        current_user.id,
    )
    return _verification_response(email_sent)


@router.post("/me/password/confirm")
def confirm_my_password_change(
    data: PasswordChangeConfirm,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    consume_account_verification(
        db=db,
        user=current_user,
        purpose=PURPOSE_PASSWORD_CHANGE,
        target_value=build_password_change_target(data.new_password),
        code=data.code,
    )

    current_user.password_hash = hash_password(data.new_password)
    _bump_session_version(current_user)
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="auth.password_changed",
        target_type="user",
        target_id=current_user.id,
    )
    db.commit()
    logger.info("Senha alterada com verificacao | user_id=%s", current_user.id)
    return {"status": "ok"}


@router.post("/me/email/request")
def request_my_email_change(
    data: EmailChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")

    new_email = _normalize_email(str(data.new_email))
    if new_email == _normalize_email(current_user.email):
        raise HTTPException(status_code=400, detail="Informe um email diferente do atual")

    exists = db.query(User).filter(User.email == new_email).first()
    if exists:
        raise HTTPException(status_code=400, detail="Não foi possível alterar para este email")

    email_sent = create_account_verification(
        db=db,
        user=current_user,
        purpose=PURPOSE_EMAIL_CHANGE,
        recipient_email=new_email,
        target_value=new_email,
    )

    logger.info(
        "Codigo de troca de email solicitado | user_id=%s | new_email=%s",
        current_user.id,
        mask_email(new_email),
    )
    return _verification_response(email_sent)


@router.post("/me/email/confirm", response_model=UserResponse)
def confirm_my_email_change(
    data: EmailChangeConfirm,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    new_email = _normalize_email(str(data.new_email))
    exists = db.query(User).filter(User.email == new_email, User.id != current_user.id).first()
    if exists:
        raise HTTPException(status_code=400, detail="Não foi possível alterar para este email")

    consume_account_verification(
        db=db,
        user=current_user,
        purpose=PURPOSE_EMAIL_CHANGE,
        target_value=new_email,
        code=data.code,
    )

    current_user.email = new_email
    current_user.email_verified = True
    current_user.email_verified_at = datetime.now(timezone.utc)
    _bump_session_version(current_user)
    record_audit_event(
        db,
        actor_id=current_user.id,
        action="auth.email_changed",
        target_type="user",
        target_id=current_user.id,
        details={"new_email": mask_email(new_email)},
    )
    db.commit()
    db.refresh(current_user)
    logger.info("Email alterado com verificacao | user_id=%s", current_user.id)
    return current_user
