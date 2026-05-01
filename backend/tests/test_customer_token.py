"""
Tests for POST /api/v1/auth/customer-token

Verifies:
- valid COMMERCE_WEBHOOK_SECRET → 200 with token
- ASSISTANT_WEBHOOK_SECRET fallback → 200 with token
- missing/wrong secret → 401, not 502
- missing tenantId → 422 (FastAPI validation)
- endpoint never calls LLM providers
"""
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to build minimal fakes without a real DB or JWT secret
# ---------------------------------------------------------------------------

def _make_shop(tenant_id: str):
    shop = MagicMock()
    shop.id = str(uuid.uuid4())
    shop.commerce_tenant_id = tenant_id
    return shop


def _env_patch(**kwargs):
    """Return a context manager that temporarily sets env vars."""
    return patch.dict(os.environ, kwargs, clear=False)


# ---------------------------------------------------------------------------
# Unit tests for _resolve_shared_secret
# ---------------------------------------------------------------------------

class TestResolveSharedSecret:
    def test_commerce_webhook_secret_wins(self, monkeypatch):
        monkeypatch.setenv("COMMERCE_WEBHOOK_SECRET", "primary-secret")
        monkeypatch.setenv("ASSISTANT_WEBHOOK_SECRET", "fallback-secret")

        # Import fresh after env change
        import importlib
        import routers.auth as auth_mod
        importlib.reload(auth_mod)

        # Patch settings inside module
        with patch.object(auth_mod.settings, "commerce_webhook_secret", "primary-secret"):
            secret, source = auth_mod._resolve_shared_secret()

        assert secret == "primary-secret"
        assert source == "COMMERCE_WEBHOOK_SECRET"

    def test_assistant_webhook_secret_fallback(self, monkeypatch):
        monkeypatch.delenv("COMMERCE_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("ASSISTANT_WEBHOOK_SECRET", "fallback-secret")

        import importlib
        import routers.auth as auth_mod
        importlib.reload(auth_mod)

        with patch.object(auth_mod.settings, "commerce_webhook_secret", ""):
            secret, source = auth_mod._resolve_shared_secret()

        assert secret == "fallback-secret"
        assert source == "ASSISTANT_WEBHOOK_SECRET"

    def test_source_none_when_neither_set(self, monkeypatch):
        monkeypatch.delenv("COMMERCE_WEBHOOK_SECRET", raising=False)
        monkeypatch.delenv("ASSISTANT_WEBHOOK_SECRET", raising=False)

        import importlib
        import routers.auth as auth_mod
        importlib.reload(auth_mod)

        with patch.object(auth_mod.settings, "commerce_webhook_secret", ""):
            secret, source = auth_mod._resolve_shared_secret()

        assert secret == ""
        assert source == "none"


# ---------------------------------------------------------------------------
# Integration-style tests using FastAPI TestClient
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """FastAPI TestClient wired with a minimal in-memory SQLite DB."""
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest")
    os.environ.setdefault("COMMERCE_WEBHOOK_SECRET", "test-shared-secret")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # Import settings after env is set so JWT_SECRET_KEY is resolved
    from core.config import Settings
    test_settings = Settings(
        jwt_secret_key="test-secret-key-for-pytest",
        commerce_webhook_secret="test-shared-secret",
    )

    from routers.auth import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _mock_db_with_shop(tenant_id: str):
    """Return an async DB session mock that finds a shop for tenant_id."""
    shop = _make_shop(tenant_id)
    scalar = MagicMock()
    scalar.scalar_one_or_none.return_value = shop
    db = AsyncMock()
    db.execute = AsyncMock(return_value=scalar)
    return db


def _mock_db_no_shop():
    """Return an async DB session mock that finds no shop."""
    scalar = MagicMock()
    scalar.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=scalar)
    return db


class TestCustomerTokenEndpoint:

    def test_valid_commerce_webhook_secret_returns_token(self):
        """COMMERCE_WEBHOOK_SECRET in header → 200 with {ok, token, expiresIn}."""
        os.environ["JWT_SECRET_KEY"] = "test-jwt-secret"
        os.environ["COMMERCE_WEBHOOK_SECRET"] = "shared-secret-123"

        import importlib
        import routers.auth as auth_mod
        importlib.reload(auth_mod)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(auth_mod.router)

        db = _mock_db_with_shop("tenant-abc")

        with patch("routers.auth.get_db", return_value=db), \
             patch.object(auth_mod.settings, "commerce_webhook_secret", "shared-secret-123"), \
             patch.object(auth_mod.settings, "jwt_secret_key", "test-jwt-secret"), \
             patch.object(auth_mod.settings, "jwt_algorithm", "HS256"), \
             patch.object(auth_mod.settings, "jwt_expiration_minutes", 60):

            client = TestClient(app)
            resp = client.post(
                "/api/v1/auth/customer-token",
                json={"commerce_tenant_id": "tenant-abc"},
                headers={"X-Thronos-Commerce-Key": "shared-secret-123"},
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get("ok") is True
        assert "token" in body
        assert isinstance(body["token"], str) and len(body["token"]) > 20
        assert body.get("expiresIn") == 3600

    def test_wrong_secret_returns_401_not_502(self):
        """Wrong X-Thronos-Commerce-Key → 401 (not a crash/502)."""
        os.environ["JWT_SECRET_KEY"] = "test-jwt-secret"
        os.environ["COMMERCE_WEBHOOK_SECRET"] = "real-secret"

        import importlib
        import routers.auth as auth_mod
        importlib.reload(auth_mod)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(auth_mod.router)

        with patch.object(auth_mod.settings, "commerce_webhook_secret", "real-secret"):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/auth/customer-token",
                json={"commerce_tenant_id": "tenant-abc"},
                headers={"X-Thronos-Commerce-Key": "WRONG-SECRET"},
            )

        assert resp.status_code == 401
        assert resp.status_code != 502

    def test_missing_secret_header_returns_401(self):
        """No X-Thronos-Commerce-Key → 401 when secret is configured."""
        import importlib
        import routers.auth as auth_mod
        importlib.reload(auth_mod)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(auth_mod.router)

        with patch.object(auth_mod.settings, "commerce_webhook_secret", "real-secret"):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/auth/customer-token",
                json={"commerce_tenant_id": "tenant-abc"},
            )

        assert resp.status_code == 401

    def test_missing_tenant_id_returns_422(self):
        """Missing commerce_tenant_id → 422 validation error, not 500."""
        import importlib
        import routers.auth as auth_mod
        importlib.reload(auth_mod)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(auth_mod.router)

        client = TestClient(app)
        resp = client.post(
            "/api/v1/auth/customer-token",
            json={},
            headers={"X-Thronos-Commerce-Key": "any"},
        )

        assert resp.status_code == 422

    def test_no_llm_import_in_auth_module(self):
        """Endpoint must not import openai, anthropic, or AI service modules."""
        import ast
        import pathlib

        src = pathlib.Path(__file__).parent.parent / "routers" / "auth.py"
        tree = ast.parse(src.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")

        llm_modules = {"openai", "anthropic", "services.ai_assistant", "services.admin_assistant_service"}
        found = {m for m in imports if any(m.startswith(lm) for lm in llm_modules)}
        assert not found, f"Auth module imports LLM deps: {found}"
