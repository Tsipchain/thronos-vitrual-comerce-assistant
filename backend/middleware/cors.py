import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# SECURITY: CORS restricted to known Thronos domains — Phase 0 hardening
# Override via CORS_ALLOW_ORIGINS env var (comma-separated) for development.
DEFAULT_ORIGINS = [
    "https://thronoschain.org",
    "https://commerce.thronoschain.org",
    "https://api.thronoschain.org",
    "https://assistant.thronoschain.org",
    "http://localhost:5173",
    "http://localhost:3000",
]


def setup_cors(app: FastAPI):
    origins = [
        o.strip()
        for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
        if o.strip()
    ] or DEFAULT_ORIGINS

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Commerce-Key"],
    )
