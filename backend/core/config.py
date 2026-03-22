import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Thronos Commerce Assistant"
    debug: bool = False
    version: str = "1.0.0"
    environment: str = "development"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str | None = None

    # Auth
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 1440

    # AI
    openai_api_key: str = ""

    # Email / SMTP
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@thronoschain.org"

    # SMS
    sms_api_key: str = ""
    sms_api_url: str = ""

    # Thronos Blockchain
    thronos_node_url: str = "https://node1.thronoschain.org"

    # CORS
    cors_allow_origins: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"

    def __getattr__(self, name: str):
        env_val = os.environ.get(name.upper())
        if env_val is not None:
            return env_val
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    @property
    def backend_url(self) -> str:
        return f"http://{self.host}:{self.port}"


settings = Settings()


def validate_environment():
    """Validate critical environment variables at startup."""
    import logging
    logger = logging.getLogger(__name__)
    warnings = []
    if not settings.database_url:
        warnings.append("DATABASE_URL not set – using in-memory SQLite")
    if settings.jwt_secret_key == "change-me-in-production":
        warnings.append("JWT_SECRET_KEY is using default – change in production")
    for w in warnings:
        logger.warning(w)
