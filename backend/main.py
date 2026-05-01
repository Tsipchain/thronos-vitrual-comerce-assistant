import importlib
import logging
import os
import pkgutil
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from core.config import settings, validate_environment
from middleware.cors import setup_cors
from services.database import initialize_database, close_database


def setup_logging():
    if os.environ.get("IS_LAMBDA") == "true":
        return
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"{log_dir}/app_{timestamp}.log"
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger(__name__)
    logger.info("=== Thronos Commerce Assistant - Logging initialized ===")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger(__name__)
    logger.info("=== Application startup initiated ===")
    validate_environment()

    # Log critical env presence (never values).
    logger.info(
        "[boot] jwt_secret_key_present=%s commerce_webhook_secret_present=%s",
        bool(getattr(settings, "jwt_secret_key", None)),
        bool(getattr(settings, "commerce_webhook_secret", None)),
    )

    try:
        await initialize_database()
        logger.info("[boot] database initialized")
    except Exception as exc:
        logger.error("[boot] database init failed (continuing without full DB): %s", type(exc).__name__)

    logger.info("=== Application startup completed ===")
    yield
    await close_database()


app = FastAPI(
    title="Thronos Commerce Assistant API",
    description="AI-powered commerce assistant for e-shop management - Part of Thronos Ecosystem",
    version="1.0.0",
    lifespan=lifespan,
)

setup_cors(app)


# ---------------------------------------------------------------------------
# Global exception handler — ensures any unhandled exception returns JSON 500
# instead of dropping the connection (which Railway logs as 502).
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger = logging.getLogger(__name__)
    logger.error(
        "[uncaught] method=%s path=%s reason=%s",
        request.method, request.url.path, type(exc).__name__,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


def include_routers_from_package(app: FastAPI, package_name: str = "routers") -> None:
    logger = logging.getLogger(__name__)
    try:
        pkg = importlib.import_module(package_name)
    except Exception as exc:
        logger.debug("Routers package '%s' not loaded: %s", package_name, exc)
        return
    discovered = 0
    for _finder, module_name, is_pkg in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        if is_pkg:
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            logger.warning("Failed to import module '%s': %s", module_name, exc)
            continue
        for attr_name in ("router", "admin_router"):
            if not hasattr(module, attr_name):
                continue
            attr = getattr(module, attr_name)
            if isinstance(attr, APIRouter):
                app.include_router(attr)
                discovered += 1
                logger.info("Included router: %s.%s", module_name, attr_name)
    logger.info("Total routers discovered: %d", discovered)


setup_logging()
include_routers_from_package(app, "routers")


@app.get("/")
def root():
    return {
        "service": "Thronos Commerce Assistant",
        "version": "1.0.0",
        "description": "AI-powered commerce assistant for e-shop management",
        "ecosystem": "Thronos",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    import services.database as _db_svc
    return {
        "status": "healthy",
        "db_ready": _db_svc.async_session is not None,
        "jwt_secret_configured": bool(getattr(settings, "jwt_secret_key", None)),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(settings.port))
