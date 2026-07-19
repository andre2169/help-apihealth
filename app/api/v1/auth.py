import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas.auth import AccountRecoveryConfirm, AccountRecoveryRequest, LoginRequest, TokenResponse
from app.schemas.user import (
    EmailChangeConfirm,
    EmailChangeRequest,
    PasswordChange,
    PasswordChangeConfirm,
    UserProfileUpdate,
    UserResponse,
)
from app.db.models.user import User
from app.core.config import settings
from app.core.request_context import get_client_ip, mask_email
from app.core.security import hash_password, verify_password

from app.services.auth_service import login_service
from app.core.exceptions import InvalidCredentials
from app.core.dependencies import get_current_user, security
from app.services.account_verification_service import (
    PURPOSE_EMAIL_CHANGE,
    PURPOSE_PASSWORD_CHANGE,
    PURPOSE_PASSWORD_RECOVERY,
    build_password_change_target,
    consume_account_verification,
    create_account_verification,
)
from app.services.token_service import revoke_token

from app.services.rate_limit_service import (
    check_login_rate_limit,
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
    response_model=TokenResponse,
)
def login(
    request: Request,
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

        response = login_service(
            db=db,
            email=data.email,
            password=data.password,
        )

        # Login deu certo
        # Zera histórico de falhas
        clear_failed_login(ip, data.email)

        logger.info(
            "Login realizado com sucesso | ip=%s | email=%s",
            ip,
            mask_email(data.email),
        )

        return response

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
    email = _normalize_email(str(data.email))
    ip = get_client_ip(request)
    user = db.query(User).filter(User.email == email).first()

    if not user:
        logger.info(
            "Recuperacao de conta solicitada para email nao cadastrado | ip=%s | email=%s",
            ip,
            mask_email(email),
        )
        return _account_recovery_response()

    email_sent = create_account_verification(
        db=db,
        user=user,
        purpose=PURPOSE_PASSWORD_RECOVERY,
        recipient_email=user.email,
        target_value=build_password_change_target(data.new_password),
    )

    logger.info(
        "Codigo de recuperacao de conta solicitado | ip=%s | user_id=%s | email=%s",
        ip,
        user.id,
        mask_email(user.email),
    )
    return _account_recovery_response(email_sent)


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
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    revoked = revoke_token(
        db=db,
        token=credentials.credentials,
        user_id=current_user.id,
    )
    logger.info(
        "Logout solicitado | user_id=%s | revoked=%s",
        current_user.id,
        revoked,
    )
    return {"status": "ok"}


@router.patch("/me", response_model=UserResponse)
def update_me(
    data: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Dados não sensíveis podem ser atualizados direto pelo perfil.
    # Email e senha usam endpoints próprios com código de confirmação.
    if data.name:
        current_user.name = data.name

    if data.phone is not None:
        current_user.phone = data.phone or None

    if data.job_title is not None:
        current_user.job_title = data.job_title or None

    if data.department is not None:
        current_user.department = data.department or None

    if data.unit_name is not None:
        current_user.unit_name = data.unit_name or None

    if data.notification_preference is not None:
        current_user.notification_preference = data.notification_preference or "email"

    if data.avatar_image is not None:
        current_user.avatar_image = data.avatar_image or None

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
    db.commit()
    db.refresh(current_user)
    logger.info("Email alterado com verificacao | user_id=%s", current_user.id)
    return current_user
