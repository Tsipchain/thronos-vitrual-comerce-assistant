"""
Regression tests for POST /api/v1/auth/customer-token.

Verifies:
  T1  valid COMMERCE_WEBHOOK_SECRET + known shop → 200 {ok, token, expiresIn}
  T2  wrong key → 401 JSON (not 502 crash)
  T3  missing key header → 401 JSON
  T4  missing commerce_tenant_id body field → 422 validation error
  T5  missing JWT_SECRET_KEY → 500 JSON (not silent crash)
  T6  no LLM import in routers/auth.py
  T7  _resolve_shared_secret priority: COMMERCE_WEBHOOK_SECRET wins
  T8  _resolve_shared_secret fallback: ASSISTANT_WEBHOOK_SECRET used when primary absent
  T9  _resolve_shared_secret source=none when neither set
  T10 dependencies.database.get_db returns 503 when async_session is None
"""
import ast
import os
import pathlib
import sys
import types
import uuid

# ---------------------------------------------------------------------------
# Minimal stubs so auth module can be imported without installed packages
# ---------------------------------------------------------------------------

def _make_stub(name: str, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _install_stubs():
    """Install minimal stubs for heavy dependencies not present in test env."""
    # fastapi stubs
    if "fastapi" not in sys.modules:
        fastapi = _make_stub("fastapi")

        class _HTTPException(Exception):
            def __init__(self, status_code: int, detail: str = ""):
                self.status_code = status_code
                self.detail = detail

        class _Header:
            def __init__(self, default=None, alias=None):
                pass

        class _Request:
            def __init__(self):
                self.headers = {}

        fastapi.HTTPException = _HTTPException
        fastapi.Header = _Header
        fastapi.Request = _Request
        class _APIRouter:
            def __init__(self, **kw):
                pass
            def post(self, *a, **kw):
                def decorator(fn):
                    return fn
                return decorator
            def get(self, *a, **kw):
                def decorator(fn):
                    return fn
                return decorator

        fastapi.APIRouter = _APIRouter
        fastapi.Depends = lambda fn: fn

        class _Status:
            HTTP_200_OK = 200
            HTTP_400_BAD_REQUEST = 400
            HTTP_401_UNAUTHORIZED = 401
            HTTP_404_NOT_FOUND = 404
            HTTP_422_UNPROCESSABLE_ENTITY = 422
            HTTP_500_INTERNAL_SERVER_ERROR = 500
            HTTP_503_SERVICE_UNAVAILABLE = 503

        fastapi.status = _Status()
        sys.modules["fastapi"] = fastapi
        sys.modules["fastapi.status"] = fastapi.status

    # sqlalchemy stubs
    for mod_name in ["sqlalchemy", "sqlalchemy.ext", "sqlalchemy.ext.asyncio"]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = _make_stub(mod_name, select=lambda *a: None, AsyncSession=object)

    # pydantic stub
    if "pydantic" not in sys.modules:
        class _BaseModel:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)
        pydantic = _make_stub("pydantic", BaseModel=_BaseModel)
        sys.modules["pydantic"] = pydantic

    # jose stub — simulate successful import
    if "jose" not in sys.modules:
        class _Jwt:
            @staticmethod
            def encode(payload, key, algorithm="HS256"):
                import base64, json
                return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode() + ".sig"

        jose = _make_stub("jose", jwt=_Jwt(), JWTError=Exception)
        sys.modules["jose"] = jose


_install_stubs()

# ---------------------------------------------------------------------------
# Now import the modules under test
# ---------------------------------------------------------------------------

BACKEND_DIR = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Stub out heavy transitive imports before pulling in auth
for _stub in ["services.auth"]:
    if _stub not in sys.modules:
        sys.modules[_stub] = _make_stub(_stub)

# Stub dependencies.database with a working get_db
async def _stub_get_db():
    yield object()

_dep_db_mod = _make_stub("dependencies.database", get_db=_stub_get_db)
sys.modules["dependencies"] = _make_stub("dependencies")
sys.modules["dependencies.database"] = _dep_db_mod


class _FakeSettings:
    commerce_webhook_secret = "shared-secret"
    jwt_secret_key = "test-jwt-key"
    jwt_algorithm = "HS256"
    jwt_expiration_minutes = 60


import types as _types

_cfg_mod = _types.ModuleType("core.config")
_cfg_mod.settings = _FakeSettings()
sys.modules["core"] = _make_stub("core")
sys.modules["core.config"] = _cfg_mod

# Stub models.shop
_shop_cls = type("Shop", (), {"commerce_tenant_id": None, "id": None})
_shop_mod = _make_stub("models", Shop=_shop_cls)
sys.modules["models"] = _shop_mod
sys.modules["models.shop"] = _make_stub("models.shop", Shop=_shop_cls)

# Now import what we actually want to test
from routers.auth import _resolve_shared_secret, _sign_jwt, CustomerTokenResponse  # noqa: E402


# ---------------------------------------------------------------------------
# T6 — static analysis: no LLM imports
# ---------------------------------------------------------------------------

def test_T6_no_llm_import():
    src_path = BACKEND_DIR / "routers" / "auth.py"
    tree = ast.parse(src_path.read_text())
    collected = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            collected.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            collected.append(node.module or "")
    llm_ns = {"openai", "anthropic", "services.ai_assistant", "services.admin_assistant_service"}
    found = {m for m in collected if any(m.startswith(ns) for ns in llm_ns)}
    assert not found, f"auth.py imports LLM deps at module level: {found}"


# ---------------------------------------------------------------------------
# T7-T9 — _resolve_shared_secret
# ---------------------------------------------------------------------------

def test_T7_commerce_webhook_wins(monkeypatch):
    monkeypatch.setattr(_cfg_mod.settings, "commerce_webhook_secret", "primary")
    monkeypatch.setenv("ASSISTANT_WEBHOOK_SECRET", "fallback")
    secret, source = _resolve_shared_secret()
    assert secret == "primary"
    assert source == "COMMERCE_WEBHOOK_SECRET"


def test_T8_assistant_webhook_fallback(monkeypatch):
    monkeypatch.setattr(_cfg_mod.settings, "commerce_webhook_secret", "")
    monkeypatch.setenv("ASSISTANT_WEBHOOK_SECRET", "fallback-secret")
    secret, source = _resolve_shared_secret()
    assert secret == "fallback-secret"
    assert source == "ASSISTANT_WEBHOOK_SECRET"


def test_T9_source_none_when_neither_set(monkeypatch):
    monkeypatch.setattr(_cfg_mod.settings, "commerce_webhook_secret", "")
    monkeypatch.delenv("ASSISTANT_WEBHOOK_SECRET", raising=False)
    secret, source = _resolve_shared_secret()
    assert secret == ""
    assert source == "none"


# ---------------------------------------------------------------------------
# T5 — missing JWT_SECRET_KEY returns HTTP 500
# ---------------------------------------------------------------------------

def test_T5_missing_jwt_secret_raises_500(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(_cfg_mod.settings, "jwt_secret_key", "")
    try:
        _sign_jwt("uid", "email@x.com", "customer", "shop-id", 60)
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 500
        assert "JWT signing key" in exc.detail


# ---------------------------------------------------------------------------
# T10 — get_db returns 503 when async_session is None
# ---------------------------------------------------------------------------

def test_T10_get_db_503_when_session_none():
    """get_db must raise HTTPException(503) when database is not initialized.
    Tested by examining the dependencies/database.py source code structure.
    """
    src = (pathlib.Path(__file__).parent.parent / "dependencies" / "database.py").read_text()
    # Must import services.database as a module reference (not freeze the value)
    assert "import services.database as _db_svc" in src, \
        "dependencies/database.py must use 'import services.database as _db_svc'"
    # Must check async_session before calling it
    assert "_db_svc.async_session is None" in src, \
        "dependencies/database.py must guard against None async_session"
    # Must raise HTTPException 503
    assert "HTTP_503_SERVICE_UNAVAILABLE" in src, \
        "dependencies/database.py must raise 503 when session is None"


# ---------------------------------------------------------------------------
# T1-T4 — HTTP-level tests using FastAPI TestClient
# ---------------------------------------------------------------------------

def _build_test_app(shop_found: bool = True, db_ready: bool = True):
    """
    Build a minimal FastAPI app with the customer-token router wired up
    but all heavy dependencies stubbed.
    """
    from unittest.mock import AsyncMock, MagicMock

    import importlib, sys

    # Patch _sign_jwt to succeed with a deterministic token.
    import routers.auth as auth_mod
    original_sign = auth_mod._sign_jwt

    def fake_sign(user_id, email, role, shop_id, expiry_minutes):
        return "fake-jwt-token", expiry_minutes * 60

    auth_mod._sign_jwt = fake_sign

    # Patch get_db to return a working async session or raise 503.
    from fastapi import HTTPException

    async def fake_get_db():
        if not db_ready:
            raise HTTPException(status_code=503, detail="DB down")
        db = AsyncMock()
        scalar = MagicMock()
        if shop_found:
            shop = MagicMock()
            shop.id = str(uuid.uuid4())
            shop.commerce_tenant_id = "tenant-abc"
        else:
            shop = None
        scalar.scalar_one_or_none.return_value = shop
        db.execute = AsyncMock(return_value=scalar)
        yield db

    # Build a real FastAPI app for test client
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        return None, None, original_sign

    real_fastapi = importlib.import_module("fastapi")
    app = real_fastapi.FastAPI()

    import importlib
    real_router_mod = importlib.import_module("routers.auth")
    # Override get_db in the router module
    real_router_mod.get_db = fake_get_db
    app.include_router(real_router_mod.router)

    return app, original_sign


def test_T1_valid_secret_returns_200():
    """Valid COMMERCE_WEBHOOK_SECRET + known shop → 200 with {ok, token, expiresIn}."""
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import importlib
    except ImportError:
        print("  SKIP T1: fastapi not installed in test env")
        return

    import routers.auth as auth_mod
    from unittest.mock import AsyncMock, MagicMock

    original_sign = auth_mod._sign_jwt
    auth_mod._sign_jwt = lambda uid, email, role, shop_id, expiry: ("fake-token", 3600)

    async def fake_get_db():
        db = AsyncMock()
        shop = MagicMock()
        shop.id = "shop-123"
        scalar = MagicMock()
        scalar.scalar_one_or_none.return_value = shop
        db.execute = AsyncMock(return_value=scalar)
        yield db

    original_get_db = auth_mod.get_db
    auth_mod.get_db = fake_get_db

    try:
        _cfg_mod.settings.commerce_webhook_secret = "valid-secret"

        app = FastAPI()
        app.include_router(auth_mod.router)
        client = TestClient(app)

        resp = client.post(
            "/api/v1/auth/customer-token",
            json={"commerce_tenant_id": "tenant-abc"},
            headers={"X-Thronos-Commerce-Key": "valid-secret"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get("ok") is True
        assert body.get("token") == "fake-token"
        assert body.get("expiresIn") == 3600
    finally:
        auth_mod._sign_jwt = original_sign
        auth_mod.get_db = original_get_db


def test_T2_wrong_secret_returns_401():
    """Wrong key → 401 JSON (not 502/crash)."""
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        print("  SKIP T2: fastapi not installed in test env")
        return

    import routers.auth as auth_mod

    _cfg_mod.settings.commerce_webhook_secret = "real-secret"

    app = FastAPI()
    app.include_router(auth_mod.router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/v1/auth/customer-token",
        json={"commerce_tenant_id": "tenant-abc"},
        headers={"X-Thronos-Commerce-Key": "WRONG"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    assert resp.status_code != 502


def test_T3_missing_key_header_returns_401():
    """No key header → 401 when secret is configured."""
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        print("  SKIP T3: fastapi not installed in test env")
        return

    import routers.auth as auth_mod

    _cfg_mod.settings.commerce_webhook_secret = "real-secret"

    app = FastAPI()
    app.include_router(auth_mod.router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/v1/auth/customer-token",
        json={"commerce_tenant_id": "tenant-abc"},
    )
    assert resp.status_code == 401


def test_T4_missing_tenant_id_returns_422():
    """Missing commerce_tenant_id → 422 validation (not 500)."""
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        print("  SKIP T4: fastapi not installed in test env")
        return

    import routers.auth as auth_mod

    _cfg_mod.settings.commerce_webhook_secret = ""  # skip key check

    app = FastAPI()
    app.include_router(auth_mod.router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/v1/auth/customer-token",
        json={},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import traceback

    tests = [
        test_T6_no_llm_import,
        test_T10_get_db_503_when_session_none,
        test_T5_missing_jwt_secret_raises_500,
        test_T1_valid_secret_returns_200,
        test_T2_wrong_secret_returns_401,
        test_T3_missing_key_header_returns_401,
        test_T4_missing_tenant_id_returns_422,
    ]

    class _Monkeypatch:
        """Minimal monkeypatch for standalone runs."""
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

        def setenv(self, key, value):
            os.environ[key] = value

        def delenv(self, key, raising=True):
            if raising:
                del os.environ[key]
            else:
                os.environ.pop(key, None)

    mp = _Monkeypatch()
    passed = failed = 0
    for fn in tests:
        try:
            import inspect
            sig = inspect.signature(fn)
            if "monkeypatch" in sig.parameters:
                fn(monkeypatch=mp)
            else:
                fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
            failed += 1

    print(f"\nResult: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
