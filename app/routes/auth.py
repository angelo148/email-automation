from __future__ import annotations

from threading import Lock
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.services.microsoft_auth_service import (
    MicrosoftAuthConfigurationError,
    MicrosoftAuthenticationRequired,
    MicrosoftWrongAccountError,
    begin_authentication,
    complete_authentication,
    is_authenticated,
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

_pending_flows: dict[
    str,
    dict[str, Any],
] = {}

_pending_flows_lock = Lock()


@router.get("/config")
async def get_auth_config() -> dict[
    str,
    str | None,
]:
    """
    Keep the existing public configuration endpoint for compatibility.

    No client secret, token, or token-cache path is exposed.
    """

    settings = get_settings()

    return {
        "client_id":
            settings.microsoft_client_id,

        "tenant_id":
            settings.microsoft_tenant_id,

        "redirect_uri":
            settings.microsoft_redirect_uri,

        "fixed_sender_email":
            settings.microsoft_fixed_sender_email,
    }


@router.get("/status")
async def get_auth_status() -> dict[
    str,
    str | bool,
]:
    """Report whether the persistent backend Microsoft session is usable."""

    settings = get_settings()

    try:
        authenticated = is_authenticated()
    except MicrosoftAuthConfigurationError:
        authenticated = False

    return {
        "authenticated":
            authenticated,

        "fixed_sender_email":
            settings.microsoft_fixed_sender_email,
    }


@router.get("/login")
async def login() -> RedirectResponse:
    """Start the one-time Microsoft sign-in."""

    flow = begin_authentication()

    state = str(
        flow.get("state", "")
    )

    if not state:
        raise MicrosoftAuthConfigurationError(
            "Microsoft authentication state was not created."
        )

    with _pending_flows_lock:
        # Single-user local application: only the newest login flow is needed.
        _pending_flows.clear()
        _pending_flows[state] = flow

    return RedirectResponse(
        url=str(flow["auth_uri"]),
        status_code=302,
    )


@router.get("/callback")
async def callback(
    request: Request,
) -> RedirectResponse:
    """Complete Microsoft's authorization-code flow."""

    state = request.query_params.get(
        "state"
    )

    if not state:
        return RedirectResponse(
            url=(
                "/?auth_error="
                + quote(
                    "Microsoft sign-in returned without a valid state."
                )
            ),
            status_code=302,
        )

    with _pending_flows_lock:
        flow = _pending_flows.pop(
            state,
            None,
        )

    if flow is None:
        return RedirectResponse(
            url=(
                "/?auth_error="
                + quote(
                    "Microsoft sign-in session expired. Please try again."
                )
            ),
            status_code=302,
        )

    try:
        await complete_authentication(
            flow=flow,
            auth_response=dict(
                request.query_params
            ),
        )

    except MicrosoftWrongAccountError as exc:
        return RedirectResponse(
            url=(
                "/?auth_error="
                + quote(str(exc))
            ),
            status_code=302,
        )

    except (
        MicrosoftAuthenticationRequired,
        MicrosoftAuthConfigurationError,
    ):
        return RedirectResponse(
            url=(
                "/?auth_error="
                + quote(
                    "Microsoft sign-in could not be completed."
                )
            ),
            status_code=302,
        )

    return RedirectResponse(
        url="/",
        status_code=302,
    )
