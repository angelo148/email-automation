from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import Settings


def configure_http(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts,
    )
