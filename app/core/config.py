import re
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core import security_policy as policy


EXAMPLE_SECRET_KEYS = {
    "exemplo_troque_por_uma_chave_longa_com_mais_de_32_caracteres",
    "gere_uma_chave_aleatoria_com_32_caracteres_ou_mais",
}

EXAMPLE_ADMIN_PASSWORDS = {
    "troque_esta_senha_antes_de_publicar",
    "senha_inicial_forte_do_administrador",
}
COOKIE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Variaveis mantidas aqui sao segredos ou dependem do ambiente de deploy.
    DATABASE_URL: str
    SECRET_KEY: str
    AUTH_COOKIE_SECURE: bool = True
    AUTH_COOKIE_SAMESITE: str = "strict"
    AUTH_COOKIE_DOMAIN: str | None = None
    ADMIN_EMAIL: str = "admin@admin.com"
    ADMIN_PASSWORD: str
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None

    # O provedor e as regras do envio ficam no codigo; as credenciais nao.
    # Mantemos apenas usuario e senha de app no ambiente.

    # Redis e integracoes externas dependem do ambiente/servico contratado.
    REDIS_URL: str | None = None
    WHATSAPP_ENABLED: bool = False
    EVOLUTION_API_URL: str | None = None
    EVOLUTION_API_KEY: str | None = None
    EVOLUTION_INSTANCE: str | None = None
    EVOLUTION_WEBHOOK_SECRET: str | None = None
    WHATSAPP_FRONTEND_BASE_URL: str = "http://localhost:5173"

    # O numero de saltos confiaveis depende do proxy da hospedagem.
    TRUSTED_PROXY_HOPS: int = 0

    @model_validator(mode="after")
    def validate_security_settings(self):
        secret_key = self.SECRET_KEY.strip()
        admin_password = self.ADMIN_PASSWORD.strip()

        if len(secret_key) < 32 or secret_key in EXAMPLE_SECRET_KEYS:
            raise ValueError(
                "SECRET_KEY insegura. Use uma chave aleatoria com pelo menos 32 caracteres."
            )

        if len(admin_password) < 12 or admin_password in EXAMPLE_ADMIN_PASSWORDS:
            raise ValueError(
                "ADMIN_PASSWORD insegura. Use uma senha inicial forte com pelo menos 12 caracteres."
            )
        if len(admin_password.encode("utf-8")) > 72:
            raise ValueError(
                "ADMIN_PASSWORD deve ter no máximo 72 bytes para ser protegida com bcrypt."
            )

        if policy.JWT_ALGORITHM != "HS256":
            raise ValueError("ALGORITHM deve ser HS256 quando SECRET_KEY e uma chave simetrica.")

        if not 5 <= policy.ACCESS_TOKEN_EXPIRE_MINUTES <= 120:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES deve ficar entre 5 e 120 minutos.")

        if not policy.JWT_ISSUER or not policy.JWT_AUDIENCE:
            raise ValueError("JWT_ISSUER e JWT_AUDIENCE nao podem ficar vazios.")

        for field_name, cookie_name in (
            ("AUTH_COOKIE_NAME", policy.AUTH_COOKIE_NAME),
            ("CSRF_COOKIE_NAME", policy.CSRF_COOKIE_NAME),
        ):
            cookie_name = cookie_name.strip()
            if not COOKIE_NAME_RE.fullmatch(cookie_name):
                raise ValueError(f"{field_name} possui um nome invalido.")

        if not policy.CSRF_HEADER_NAME or len(policy.CSRF_HEADER_NAME) > 80:
            raise ValueError("CSRF_HEADER_NAME possui um valor invalido.")

        if self.AUTH_COOKIE_DOMAIN is not None and not self.AUTH_COOKIE_DOMAIN.strip():
            self.AUTH_COOKIE_DOMAIN = None

        if self.TRUSTED_PROXY_HOPS < 0:
            raise ValueError("TRUSTED_PROXY_HOPS nao pode ser negativo.")

        same_site = self.AUTH_COOKIE_SAMESITE.strip().lower()
        if same_site not in {"strict", "lax", "none"}:
            raise ValueError("AUTH_COOKIE_SAMESITE deve ser strict, lax ou none.")
        self.AUTH_COOKIE_SAMESITE = same_site

        if same_site == "none" and not self.AUTH_COOKIE_SECURE:
            raise ValueError("AUTH_COOKIE_SAMESITE=none exige AUTH_COOKIE_SECURE=true.")

        if policy.ACCOUNT_RECOVERY_MIN_RESPONSE_SECONDS < 0:
            raise ValueError("ACCOUNT_RECOVERY_MIN_RESPONSE_SECONDS nao pode ser negativo.")

        if policy.ACCOUNT_RECOVERY_WINDOW_SECONDS < 60:
            raise ValueError("ACCOUNT_RECOVERY_WINDOW_SECONDS precisa ter pelo menos 60 segundos.")

        if policy.ACCOUNT_RECOVERY_MAX_REQUESTS_PER_EMAIL < 1:
            raise ValueError("ACCOUNT_RECOVERY_MAX_REQUESTS_PER_EMAIL precisa ser maior que zero.")

        if policy.ACCOUNT_RECOVERY_MAX_REQUESTS_PER_IP < 1:
            raise ValueError("ACCOUNT_RECOVERY_MAX_REQUESTS_PER_IP precisa ser maior que zero.")

        if self.REDIS_URL is not None:
            redis_url = self.REDIS_URL.strip()
            if not redis_url:
                self.REDIS_URL = None
            elif not redis_url.startswith(("redis://", "rediss://")):
                raise ValueError("REDIS_URL deve comecar com redis:// ou rediss://.")
            else:
                self.REDIS_URL = redis_url


        self.WHATSAPP_FRONTEND_BASE_URL = self.WHATSAPP_FRONTEND_BASE_URL.strip().rstrip("/")
        if not self.WHATSAPP_FRONTEND_BASE_URL.startswith(("http://", "https://")):
            raise ValueError("WHATSAPP_FRONTEND_BASE_URL deve começar com http:// ou https://.")

        if policy.WHATSAPP_MAX_ATTEMPTS < 1 or policy.WHATSAPP_MAX_ATTEMPTS > 10:
            raise ValueError("WHATSAPP_MAX_ATTEMPTS deve ficar entre 1 e 10.")

        if policy.WHATSAPP_RETRY_BASE_SECONDS < 1:
            raise ValueError("WHATSAPP_RETRY_BASE_SECONDS precisa ser maior que zero.")

        if policy.EVOLUTION_TIMEOUT_SECONDS < 5 or policy.EVOLUTION_TIMEOUT_SECONDS > 60:
            raise ValueError("EVOLUTION_TIMEOUT_SECONDS deve ficar entre 5 e 60 segundos.")

        if policy.WHATSAPP_QUEUE_LEASE_SECONDS < 30:
            raise ValueError("WHATSAPP_QUEUE_LEASE_SECONDS precisa ter pelo menos 30 segundos.")

        if policy.WHATSAPP_WORKER_LEASE_SECONDS < 30:
            raise ValueError("WHATSAPP_WORKER_LEASE_SECONDS precisa ter pelo menos 30 segundos.")

        if policy.WHATSAPP_WORKER_POLL_SECONDS <= 0:
            raise ValueError("WHATSAPP_WORKER_POLL_SECONDS precisa ser maior que zero.")

        if policy.WHATSAPP_WORKER_BATCH_SIZE < 1 or policy.WHATSAPP_WORKER_BATCH_SIZE > 100:
            raise ValueError("WHATSAPP_WORKER_BATCH_SIZE deve ficar entre 1 e 100.")

        if policy.WHATSAPP_STREAM_MAXLEN < 100:
            raise ValueError("WHATSAPP_STREAM_MAXLEN precisa ser pelo menos 100.")

        if self.WHATSAPP_ENABLED:
            if not self.REDIS_URL:
                raise ValueError("REDIS_URL é obrigatória quando WHATSAPP_ENABLED=true.")
            if not self.EVOLUTION_API_URL:
                raise ValueError("EVOLUTION_API_URL é obrigatória quando WHATSAPP_ENABLED=true.")
            if not self.EVOLUTION_API_KEY:
                raise ValueError("EVOLUTION_API_KEY é obrigatória quando WHATSAPP_ENABLED=true.")
            if not self.EVOLUTION_INSTANCE:
                raise ValueError("EVOLUTION_INSTANCE é obrigatória quando WHATSAPP_ENABLED=true.")
            if not self.EVOLUTION_WEBHOOK_SECRET:
                raise ValueError(
                    "EVOLUTION_WEBHOOK_SECRET é obrigatória quando WHATSAPP_ENABLED=true."
                )

        if self.EVOLUTION_API_URL:
            self.EVOLUTION_API_URL = self.EVOLUTION_API_URL.strip().rstrip("/")
            parsed_evolution_url = urlsplit(self.EVOLUTION_API_URL)
            if (
                not parsed_evolution_url.hostname
                or parsed_evolution_url.username
                or parsed_evolution_url.password
                or parsed_evolution_url.query
                or parsed_evolution_url.fragment
            ):
                raise ValueError("EVOLUTION_API_URL possui um formato invalido.")
            local_hosts = {"localhost", "127.0.0.1", "::1"}
            if parsed_evolution_url.scheme != "https" and not (
                parsed_evolution_url.scheme == "http"
                and parsed_evolution_url.hostname.lower() in local_hosts
            ):
                raise ValueError(
                    "EVOLUTION_API_URL deve usar HTTPS; HTTP so e permitido em loopback local."
                )

        if self.EVOLUTION_API_KEY:
            self.EVOLUTION_API_KEY = self.EVOLUTION_API_KEY.strip()

        if self.EVOLUTION_INSTANCE:
            self.EVOLUTION_INSTANCE = self.EVOLUTION_INSTANCE.strip()

        if self.EVOLUTION_WEBHOOK_SECRET:
            self.EVOLUTION_WEBHOOK_SECRET = self.EVOLUTION_WEBHOOK_SECRET.strip()

        if policy.STARTUP_LOCK_TIMEOUT_SECONDS < 1:
            raise ValueError("STARTUP_LOCK_TIMEOUT_SECONDS precisa ser maior que zero.")

        if policy.STARTUP_LOCK_STALE_SECONDS < policy.STARTUP_LOCK_TIMEOUT_SECONDS:
            raise ValueError(
                "STARTUP_LOCK_STALE_SECONDS precisa ser maior ou igual ao timeout do lock."
            )

        if policy.SMTP_USE_TLS and policy.SMTP_USE_SSL:
            raise ValueError("Use apenas SMTP_USE_TLS ou SMTP_USE_SSL, nunca os dois juntos.")

        if self.SMTP_USERNAME or self.SMTP_PASSWORD:
            smtp_host = policy.SMTP_HOST
            if policy.SMTP_TIMEOUT_SECONDS < 5:
                raise ValueError("SMTP_TIMEOUT_SECONDS precisa ser maior ou igual a 5.")

            if smtp_host == "smtp.gmail.com":
                if not (self.SMTP_USERNAME and self.SMTP_PASSWORD):
                    raise ValueError(
                        "Gmail SMTP exige SMTP_USERNAME e SMTP_PASSWORD com senha de app."
                    )
                if policy.SMTP_PORT == 587 and not policy.SMTP_USE_TLS:
                    raise ValueError("Gmail na porta 587 exige SMTP_USE_TLS=true.")
                if policy.SMTP_PORT == 465 and not policy.SMTP_USE_SSL:
                    raise ValueError("Gmail na porta 465 exige SMTP_USE_SSL=true.")
                if policy.SMTP_PORT not in {465, 587}:
                    raise ValueError("Gmail SMTP deve usar porta 587 com TLS ou 465 com SSL.")

        return self

    @property
    def allowed_origins(self) -> list[str]:
        origins = [
            origin.strip().rstrip("/")
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

        if "*" in origins:
            raise ValueError(
                "ALLOWED_ORIGINS nao pode usar '*'. Informe a URL exata do frontend."
            )

        if self.AUTH_COOKIE_SECURE:
            insecure_origins = [
                origin
                for origin in origins
                if not origin.startswith("https://")
                and origin not in {"http://localhost:5173", "http://127.0.0.1:5173"}
            ]
            if insecure_origins:
                raise ValueError(
                    "AUTH_COOKIE_SECURE=true exige ALLOWED_ORIGINS HTTPS "
                    "(exceto localhost para testes locais)."
                )

        return origins

    @property
    def local_login_mfa_code_logging(self) -> bool:
        """Expose login MFA codes only for a strictly local SQLite setup."""
        if urlsplit(self.DATABASE_URL.strip()).scheme not in {"sqlite", "sqlite+pysqlite"}:
            return False

        origins = self.allowed_origins
        if not origins:
            return False

        local_hosts = {"localhost", "127.0.0.1", "::1"}
        for origin in origins:
            parsed = urlsplit(origin)
            try:
                parsed.port
            except ValueError:
                return False
            if (
                parsed.scheme != "http"
                or parsed.hostname not in local_hosts
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                return False

        return True

    @property
    def smtp_configured(self) -> bool:
        return bool(
            self.SMTP_USERNAME
            and self.SMTP_PASSWORD
        )

    @property
    def whatsapp_configured(self) -> bool:
        return bool(
            self.WHATSAPP_ENABLED
            and self.REDIS_URL
            and self.EVOLUTION_API_URL
            and self.EVOLUTION_API_KEY
            and self.EVOLUTION_INSTANCE
        )


settings = Settings()
