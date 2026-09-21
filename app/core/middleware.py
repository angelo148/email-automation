import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.request_context import request_id_var


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request ID for logs and error responses."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "").strip()
        request_id = incoming or str(uuid.uuid7())

        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)

        response.headers["X-Request-ID"] = request_id
        return response
