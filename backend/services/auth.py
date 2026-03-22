import logging
from datetime import datetime, timedelta

from jose import jwt

from core.config import settings

logger = logging.getLogger(__name__)


def create_access_token(user_id: str, email: str, role: str = "merchant", shop_id: str | None = None) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "shop_id": shop_id,
        "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_expiration_minutes),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
