from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Banco de dados
    DATABASE_URL: str

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Seed / admin inicial
    ADMIN_EMAIL: str = "admin@admin.com"
    ADMIN_PASSWORD: str

    # CORS - lista de origens separadas por vírgula
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Superficie publica da API.
    # Em producao, deixe a documentacao e o health check do banco desligados.
    ENABLE_API_DOCS: bool = False
    ENABLE_DB_HEALTH_ENDPOINT: bool = False
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
    MAIL_FROM: str | None = None
    MAIL_FROM_NAME: str = "HelpWeb Health"
    REPLY_TO_EMAIL: str | None = None
    EMAIL_CODE_EXPIRE_MINUTES: int = 15
    VERIFICATION_RESEND_COOLDOWN_SECONDS: int = 300

    # Rate limit em memória. Funciona bem para o deploy simples em uma instância.
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_MAX_REQUESTS: int = 240
    RATE_LIMIT_SENSITIVE_MAX_REQUESTS: int = 40
    # Use 0 para ignorar headers enviados pelo cliente. Se a hospedagem
    # confirmar um proxy confiavel adicionando X-Forwarded-For, use 1.
    TRUSTED_PROXY_HOPS: int = 0

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
        return bool(self.SMTP_HOST and self.MAIL_FROM)


settings = Settings()
