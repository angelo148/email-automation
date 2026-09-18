from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.http import configure_http
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.routes.auth import router as auth_router
from app.routes.companies import router as companies_router
from app.routes.email import router as email_router
from app.routes.health import router as health_router
from app.routes.web import router as web_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    settings = get_settings()

    configure_logging(settings.log_level)

    logger = get_logger(__name__)

    logger.debug(
        "Starting %s version %s in %s environment.",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )

    docs_enabled = settings.environment != "production"

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        docs_url=("/docs" if docs_enabled else None),
        redoc_url=("/redoc" if docs_enabled else None),
        openapi_url=("/openapi.json" if docs_enabled else None),
    )

    application.mount(
        "/static",
        StaticFiles(directory="app/static"),
        name="static",
    )

    configure_http(
        application,
        settings,
    )

    application.add_middleware(RequestContextMiddleware)

    register_exception_handlers(application)

    application.include_router(health_router)
    application.include_router(companies_router)
    application.include_router(email_router)
    application.include_router(web_router)
    application.include_router(auth_router)

    logger.debug("Application initialized successfully.")

    return application


app = create_app()
