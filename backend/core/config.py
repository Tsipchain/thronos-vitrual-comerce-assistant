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

    # Database – Railway PostgreSQL plugin exposes the URL under several names;
    # database.py checks all four in priority order.
    database_url: str | None = None          # DATABASE_URL
    postgres_url: str | None = None          # POSTGRES_URL  (Railway default)
    database_private_url: str | None = None  # DATABASE_PRIVATE_URL
    database_public_url: str | None = None   # DATABASE_PUBLIC_URL

    # Auth
    # SECURITY: Default JWT secret removed — Phase 0 hardening
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 1440

    # AI — OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # AI — Anthropic (Claude). Takes priority over OpenAI when set.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

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

    # Commerce → Assistant webhook shared secret
    commerce_webhook_secret: str = ""

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

    # Check whether *any* Railway DB URL var is set.
    _db_url_vars = [
        "DATABASE_URL",
        "POSTGRES_URL",
        "DATABASE_PRIVATE_URL",
        "DATABASE_PUBLIC_URL",
    ]
    has_db = any(
        getattr(settings, var.lower(), None) or os.environ.get(var)
        for var in _db_url_vars
    )

    warnings = []
    if not has_db:
        warnings.append(
            "No database URL configured (checked: " + ", ".join(_db_url_vars) + ") – "
            "using in-memory SQLite; data will not persist"
        )
    # SECURITY: Default JWT secret removed — Phase 0 hardening
    # jwt_secret_key is now a required field (no default) so pydantic will
    # raise ValidationError at startup if JWT_SECRET_KEY is not set.
    if not settings.anthropic_api_key and not settings.openai_api_key:
        warnings.append("Neither ANTHROPIC_API_KEY nor OPENAI_API_KEY set – assistant will use keyword fallback only")
    # SECURITY: Webhook secret now required — Phase 0 hardening
    if not settings.commerce_webhook_secret:
        warnings.append("COMMERCE_WEBHOOK_SECRET not set – webhook endpoints will reject all requests")

    for w in warnings:
        logger.warning(w)
