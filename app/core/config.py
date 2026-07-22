from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


EXAMPLE_SECRET_KEYS = {
    "exemplo_troque_por_uma_chave_longa_com_mais_de_32_caracteres",
    "gere_uma_chave_aleatoria_com_32_caracteres_ou_mais",
}

EXAMPLE_ADMIN_PASSWORDS = {
    "troque_esta_senha_antes_de_publicar",
    "senha_inicial_forte_do_administrador",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Banco de dados
    DATABASE_URL: str
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_POOL_RECYCLE_SECONDS: int = 1800

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    AUTH_COOKIE_NAME: str = "helpwebhealth_session"
    AUTH_COOKIE_SECURE: bool = True
    AUTH_COOKIE_SAMESITE: str = "strict"
    AUTH_COOKIE_DOMAIN: str | None = None

    # Seed / admin inicial
    ADMIN_EMAIL: str = "admin@admin.com"
    ADMIN_PASSWORD: str

    # CORS - lista de origens separadas por vírgula
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Superficie publica da API.
    # Em producao, deixe a documentacao e o health check do banco desligados.
    ENABLE_API_DOCS: bool = False
    ENABLE_DB_HEALTH_ENDPOINT: bool = False
    ENABLE_NETWORK_DEBUG_ENDPOINT: bool = False
    API_DOCS_USERNAME: str = "admin"
    API_DOCS_PASSWORD: str | None = None

    # Logs: "text" para leitura simples na Shard ou "json" para monitoramento.
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"
    ALLOW_LOG_VERIFICATION_CODES: bool = False

    # Email / códigos de verificação
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: int = 30
    MAIL_FROM: str | None = None
    MAIL_FROM_NAME: str = "HelpWeb Health"
    REPLY_TO_EMAIL: str | None = None
    EMAIL_CODE_EXPIRE_MINUTES: int = 15
    VERIFICATION_RESEND_COOLDOWN_SECONDS: int = 300
    ACCOUNT_RECOVERY_MIN_RESPONSE_SECONDS: float = 1.2
    ACCOUNT_RECOVERY_WINDOW_SECONDS: int = 900
    ACCOUNT_RECOVERY_MAX_REQUESTS_PER_EMAIL: int = 5
    ACCOUNT_RECOVERY_MAX_REQUESTS_PER_IP: int = 20

    # Rate limit em memória. Funciona bem para o deploy simples em uma instância.
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_MAX_REQUESTS: int = 240
    RATE_LIMIT_SENSITIVE_MAX_REQUESTS: int = 40
    RATE_LIMIT_PUBLIC_MAX_REQUESTS: int = 120
    RATE_LIMIT_POLLING_MAX_REQUESTS: int = 80
    REDIS_URL: str | None = None
    REDIS_RATE_LIMIT_PREFIX: str = "helpwebhealth:rate"
    REDIS_CONNECT_TIMEOUT_SECONDS: float = 1.0
    REDIS_OPERATION_TIMEOUT_SECONDS: float = 1.0
    MAX_CONCURRENT_REQUESTS: int = 80
    CONCURRENCY_WAIT_TIMEOUT_SECONDS: float = 0.25
    MAX_REQUEST_BODY_BYTES: int = 6_000_000
    MAX_REQUEST_URL_BYTES: int = 2048
    MAX_REQUEST_HEADER_BYTES: int = 32_000
    MAX_REQUEST_HEADER_VALUE_BYTES: int = 8_000
    MAX_TICKET_IMAGE_TICKETS_PER_USER_DAY: int = 12
    # Use 0 para ignorar headers enviados pelo cliente. Se a hospedagem
    # confirmar um proxy confiavel adicionando X-Forwarded-For, use 1.
    TRUSTED_PROXY_HOPS: int = 0

    # Inicializacao. No deploy simples da Shard, as migracoes rodam no boot,
    # protegidas por lock de arquivo para evitar corrida entre processos.
    RUN_MIGRATIONS_ON_STARTUP: bool = True
    STARTUP_LOCK_PATH: str | None = None
    STARTUP_LOCK_TIMEOUT_SECONDS: int = 120
    STARTUP_LOCK_STALE_SECONDS: int = 300

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

        if self.AUTH_COOKIE_DOMAIN is not None and not self.AUTH_COOKIE_DOMAIN.strip():
            self.AUTH_COOKIE_DOMAIN = None

        if self.API_DOCS_PASSWORD is not None and not self.API_DOCS_PASSWORD.strip():
            self.API_DOCS_PASSWORD = None

        if self.ENABLE_API_DOCS and not (self.API_DOCS_PASSWORD and self.API_DOCS_PASSWORD.strip()):
            raise ValueError(
                "API_DOCS_PASSWORD e obrigatoria quando ENABLE_API_DOCS=true."
            )

        if self.TRUSTED_PROXY_HOPS < 0:
            raise ValueError("TRUSTED_PROXY_HOPS nao pode ser negativo.")

        if self.DB_POOL_SIZE < 1:
            raise ValueError("DB_POOL_SIZE precisa ser maior que zero.")

        if self.DB_MAX_OVERFLOW < 0:
            raise ValueError("DB_MAX_OVERFLOW nao pode ser negativo.")

        if self.DB_POOL_TIMEOUT_SECONDS < 1:
            raise ValueError("DB_POOL_TIMEOUT_SECONDS precisa ser maior que zero.")

        if self.DB_POOL_RECYCLE_SECONDS < 60:
            raise ValueError("DB_POOL_RECYCLE_SECONDS precisa ter pelo menos 60 segundos.")

        same_site = self.AUTH_COOKIE_SAMESITE.strip().lower()
        if same_site not in {"strict", "lax", "none"}:
            raise ValueError("AUTH_COOKIE_SAMESITE deve ser strict, lax ou none.")
        self.AUTH_COOKIE_SAMESITE = same_site

        if same_site == "none" and not self.AUTH_COOKIE_SECURE:
            raise ValueError("AUTH_COOKIE_SAMESITE=none exige AUTH_COOKIE_SECURE=true.")

        if self.ACCOUNT_RECOVERY_MIN_RESPONSE_SECONDS < 0:
            raise ValueError("ACCOUNT_RECOVERY_MIN_RESPONSE_SECONDS nao pode ser negativo.")

        if self.ACCOUNT_RECOVERY_WINDOW_SECONDS < 60:
            raise ValueError("ACCOUNT_RECOVERY_WINDOW_SECONDS precisa ter pelo menos 60 segundos.")

        if self.ACCOUNT_RECOVERY_MAX_REQUESTS_PER_EMAIL < 1:
            raise ValueError("ACCOUNT_RECOVERY_MAX_REQUESTS_PER_EMAIL precisa ser maior que zero.")

        if self.ACCOUNT_RECOVERY_MAX_REQUESTS_PER_IP < 1:
            raise ValueError("ACCOUNT_RECOVERY_MAX_REQUESTS_PER_IP precisa ser maior que zero.")

        if self.RATE_LIMIT_WINDOW_SECONDS < 1:
            raise ValueError("RATE_LIMIT_WINDOW_SECONDS precisa ser maior que zero.")

        for field_name in (
            "RATE_LIMIT_MAX_REQUESTS",
            "RATE_LIMIT_SENSITIVE_MAX_REQUESTS",
            "RATE_LIMIT_PUBLIC_MAX_REQUESTS",
            "RATE_LIMIT_POLLING_MAX_REQUESTS",
        ):
            if getattr(self, field_name) < 1:
                raise ValueError(f"{field_name} precisa ser maior que zero.")

        if self.REDIS_URL is not None:
            redis_url = self.REDIS_URL.strip()
            if not redis_url:
                self.REDIS_URL = None
            elif not redis_url.startswith(("redis://", "rediss://")):
                raise ValueError("REDIS_URL deve comecar com redis:// ou rediss://.")
            else:
                self.REDIS_URL = redis_url

        self.REDIS_RATE_LIMIT_PREFIX = self.REDIS_RATE_LIMIT_PREFIX.strip() or "helpwebhealth:rate"

        if self.REDIS_CONNECT_TIMEOUT_SECONDS <= 0:
            raise ValueError("REDIS_CONNECT_TIMEOUT_SECONDS precisa ser maior que zero.")

        if self.REDIS_OPERATION_TIMEOUT_SECONDS <= 0:
            raise ValueError("REDIS_OPERATION_TIMEOUT_SECONDS precisa ser maior que zero.")

        if self.MAX_CONCURRENT_REQUESTS < 1:
            raise ValueError("MAX_CONCURRENT_REQUESTS precisa ser maior que zero.")

        if self.CONCURRENCY_WAIT_TIMEOUT_SECONDS <= 0:
            raise ValueError("CONCURRENCY_WAIT_TIMEOUT_SECONDS precisa ser maior que zero.")

        if self.MAX_REQUEST_BODY_BYTES < 100_000:
            raise ValueError("MAX_REQUEST_BODY_BYTES precisa ter pelo menos 100000 bytes.")

        if self.MAX_REQUEST_URL_BYTES < 512:
            raise ValueError("MAX_REQUEST_URL_BYTES precisa ter pelo menos 512 bytes.")

        if self.MAX_REQUEST_HEADER_BYTES < 4096:
            raise ValueError("MAX_REQUEST_HEADER_BYTES precisa ter pelo menos 4096 bytes.")

        if self.MAX_REQUEST_HEADER_VALUE_BYTES < 1024:
            raise ValueError("MAX_REQUEST_HEADER_VALUE_BYTES precisa ter pelo menos 1024 bytes.")

        if self.MAX_TICKET_IMAGE_TICKETS_PER_USER_DAY < 1:
            raise ValueError("MAX_TICKET_IMAGE_TICKETS_PER_USER_DAY precisa ser maior que zero.")

        if self.STARTUP_LOCK_TIMEOUT_SECONDS < 1:
            raise ValueError("STARTUP_LOCK_TIMEOUT_SECONDS precisa ser maior que zero.")

        if self.STARTUP_LOCK_STALE_SECONDS < self.STARTUP_LOCK_TIMEOUT_SECONDS:
            raise ValueError(
                "STARTUP_LOCK_STALE_SECONDS precisa ser maior ou igual ao timeout do lock."
            )

        if self.SMTP_USE_TLS and self.SMTP_USE_SSL:
            raise ValueError("Use apenas SMTP_USE_TLS ou SMTP_USE_SSL, nunca os dois juntos.")

        if self.SMTP_HOST:
            smtp_host = self.SMTP_HOST.strip().lower()
            if self.SMTP_TIMEOUT_SECONDS < 5:
                raise ValueError("SMTP_TIMEOUT_SECONDS precisa ser maior ou igual a 5.")

            if smtp_host == "smtp.gmail.com":
                if not (self.SMTP_USERNAME and self.SMTP_PASSWORD):
                    raise ValueError(
                        "Gmail SMTP exige SMTP_USERNAME e SMTP_PASSWORD com senha de app."
                    )
                if self.SMTP_PORT == 587 and not self.SMTP_USE_TLS:
                    raise ValueError("Gmail na porta 587 exige SMTP_USE_TLS=true.")
                if self.SMTP_PORT == 465 and not self.SMTP_USE_SSL:
                    raise ValueError("Gmail na porta 465 exige SMTP_USE_SSL=true.")
                if self.SMTP_PORT not in {465, 587}:
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

        return origins

    @property
    def smtp_configured(self) -> bool:
        return bool(
            self.SMTP_HOST
            and self.MAIL_FROM
            and self.SMTP_USERNAME
            and self.SMTP_PASSWORD
        )


settings = Settings()
