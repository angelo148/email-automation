import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import get_request_id
from app.services.email_service import (
    EmailConfigurationError,
    EmailPreviewError,
    EmailSendError,
)
from app.services.excel_service import ExcelValidationError


logger = logging.getLogger("app.exceptions")


def _request_id_from(request: Request) -> str:
    """Return the request ID associated with the current request."""

    return getattr(request.state, "request_id", None) or get_request_id()


def _error_payload(detail: str, request_id: str) -> dict[str, str]:
    """Create a standard API error response."""

    return {"detail": detail, "request_id": request_id}


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """
    Convert FastAPI/Pydantic validation errors into safe JSON data.

    Raw input values and Pydantic context are intentionally excluded.

    This prevents:
    - non-serializable Python exceptions from reaching JSONResponse;
    - sensitive request values from being echoed back to the client.
    """

    safe_errors: list[dict[str, Any]] = []

    for error in exc.errors():
        safe_errors.append(
            {
                "type": str(error.get("type", "validation_error")),
                "loc": list(error.get("loc", ())),
                "msg": str(error.get("msg", "Invalid value.")),
            }
        )

    return safe_errors


def register_exception_handlers(app: FastAPI) -> None:
    """Register centralized application exception handlers."""

    @app.exception_handler(EmailPreviewError)
    async def preview_error_handler(
        request: Request,
        exc: EmailPreviewError,
    ) -> JSONResponse:
        request_id = _request_id_from(request)

        return JSONResponse(
            status_code=400,
            content=_error_payload(str(exc), request_id),
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(ExcelValidationError)
    async def excel_error_handler(
        request: Request,
        exc: ExcelValidationError,
    ) -> JSONResponse:
        request_id = _request_id_from(request)

        logger.warning("Excel validation failed: %s", exc)

        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "The recipient workbook is invalid.",
                request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(FileNotFoundError)
    async def missing_file_handler(
        request: Request,
        exc: FileNotFoundError,
    ) -> JSONResponse:
        request_id = _request_id_from(request)

        logger.error("Required file was not found: %s", exc)

        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "Third-party Excel file was not found.",
                request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(EmailConfigurationError)
    async def email_config_handler(
        request: Request,
        exc: EmailConfigurationError,
    ) -> JSONResponse:
        request_id = _request_id_from(request)

        logger.error("Email configuration error: %s", exc)

        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "Email sending is not configured.",
                request_id,
            ),
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(EmailSendError)
    async def email_send_handler(
        request: Request,
        exc: EmailSendError,
    ) -> JSONResponse:
        request_id = _request_id_from(request)

        logger.error("Email send failed: %s", exc)

        return JSONResponse(
            status_code=502,
            content=_error_payload("Email sending failed.", request_id),
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id = _request_id_from(request)

        logger.debug(
            "Request validation failed for %s %s.",
            request.method,
            request.url.path,
        )

        return JSONResponse(
            status_code=422,
            content={
                "detail": _safe_validation_errors(exc),
                "request_id": request_id,
            },
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        request_id = _request_id_from(request)

        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."

        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(detail, request_id),
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        request_id = _request_id_from(request)

        logger.exception(
            "Unhandled application exception. Request ID: %s",
            request_id,
        )

        return JSONResponse(
            status_code=500,
            content=_error_payload("Internal server error.", request_id),
            headers={"X-Request-ID": request_id},
        )