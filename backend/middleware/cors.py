import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# SECURITY: CORS restricted to known Thronos domains and active tenant domains.
# Add extra origins via CORS_ALLOW_ORIGINS env var (comma-separated) — merged with defaults.
DEFAULT_ORIGINS = [
    "https://thronoschain.org",
    "https://commerce.thronoschain.org",
    "https://api.thronoschain.org",
    "https://assistant.thronoschain.org",
    # Active tenant domains
    "https://eukolaki.gr",
    "https://www.eukolaki.gr",
]


def setup_cors(app: FastAPI):
    extra = [
        o.strip()
        for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
        if o.strip()
    ]
    origins = list(dict.fromkeys(DEFAULT_ORIGINS + extra))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Commerce-Key"],
    )
