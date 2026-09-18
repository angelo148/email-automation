from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import msal
from msal_extensions import (
    PersistedTokenCache,
    build_encrypted_persistence,
)

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

MICROSOFT_AUTHORITY = "https://login.microsoftonline.com/consumers"

MICROSOFT_SCOPES = [
    "User.Read",
    "Mail.Send",
]

GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"

GRAPH_TIMEOUT_SECONDS = 20.0


class MicrosoftAuthConfigurationError(RuntimeError):
    """Raised when required Microsoft OAuth settings are missing."""


class MicrosoftAuthenticationRequired(RuntimeError):
    """Raised when the user must authenticate interactively."""


class MicrosoftWrongAccountError(RuntimeError):
    """Raised when Microsoft authenticated a different mailbox."""


def _normalized_email(value: str) -> str:
    return value.strip().casefold()


def _validate_configuration() -> None:
    settings = get_settings()

    if not settings.microsoft_client_id:
        raise MicrosoftAuthConfigurationError("MICROSOFT_CLIENT_ID is not configured.")

    if not settings.microsoft_client_secret:
        raise MicrosoftAuthConfigurationError(
            "MICROSOFT_CLIENT_SECRET is not configured."
        )

    if not settings.microsoft_callback_uri:
        raise MicrosoftAuthConfigurationError(
            "MICROSOFT_CALLBACK_URI is not configured."
        )

    if not settings.microsoft_fixed_sender_email:
        raise MicrosoftAuthConfigurationError(
            "MICROSOFT_FIXED_SENDER_EMAIL is not configured."
        )


@lru_cache
def _get_token_cache() -> PersistedTokenCache:
    """
    Return the persistent encrypted MSAL token cache.

    On Windows, msal-extensions uses DPAPI. This means the cache remains
    available after Edge and FastAPI are closed, while being protected for
    the current Windows user.
    """

    settings = get_settings()

    cache_path = Path(settings.microsoft_token_cache_file)

    cache_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    persistence = build_encrypted_persistence(str(cache_path))

    if not persistence.is_encrypted:
        raise MicrosoftAuthConfigurationError(
            "Microsoft token cache encryption is unavailable."
        )

    return PersistedTokenCache(persistence)


@lru_cache
def get_microsoft_app() -> msal.ConfidentialClientApplication:
    """Build the server-side confidential Microsoft OAuth client."""

    _validate_configuration()

    settings = get_settings()

    return msal.ConfidentialClientApplication(
        client_id=settings.microsoft_client_id,
        client_credential=(settings.microsoft_client_secret),
        authority=MICROSOFT_AUTHORITY,
        token_cache=_get_token_cache(),
    )


def _get_fixed_sender_account() -> dict[str, Any] | None:
    settings = get_settings()
    expected = _normalized_email(settings.microsoft_fixed_sender_email)

    accounts = get_microsoft_app().get_accounts()

    for account in accounts:
        username = str(account.get("username", ""))

        if _normalized_email(username) == expected:
            return account

    return None


def begin_authentication() -> dict[str, Any]:
    """Start Microsoft authorization-code flow for the fixed sender."""

    settings = get_settings()
    app = get_microsoft_app()

    flow = app.initiate_auth_code_flow(
        scopes=MICROSOFT_SCOPES,
        redirect_uri=(settings.microsoft_callback_uri),
        login_hint=(settings.microsoft_fixed_sender_email),
    )

    if "auth_uri" not in flow:
        logger.error("Microsoft did not return an auth_uri while starting login.")

        raise MicrosoftAuthConfigurationError("Microsoft sign-in could not be started.")

    return flow


async def _resolve_graph_sender(
    access_token: str,
) -> str:
    """Resolve the signed-in Microsoft mailbox using Graph /me."""

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(
        timeout=GRAPH_TIMEOUT_SECONDS,
    ) as client:
        try:
            response = await client.get(
                GRAPH_ME_URL,
                headers=headers,
                params={"$select": "mail,userPrincipalName"},
            )
        except httpx.RequestError as exc:
            raise MicrosoftAuthenticationRequired(
                "Microsoft Graph could not be reached."
            ) from exc

    if response.status_code in {
        401,
        403,
    }:
        raise MicrosoftAuthenticationRequired(
            "Microsoft authentication is no longer valid."
        )

    if not response.is_success:
        logger.error(
            "Graph /me failed during authentication with HTTP %d.",
            response.status_code,
        )

        raise MicrosoftAuthenticationRequired(
            "Microsoft could not validate the signed-in account."
        )

    data = response.json()

    sender = data.get("mail") or data.get("userPrincipalName") or ""

    if not sender:
        raise MicrosoftAuthenticationRequired(
            "Microsoft did not return an email address for the account."
        )

    return str(sender)


def _remove_non_fixed_accounts() -> None:
    """Remove unexpected accounts from the backend token cache."""

    settings = get_settings()
    expected = _normalized_email(settings.microsoft_fixed_sender_email)

    app = get_microsoft_app()

    for account in app.get_accounts():
        username = str(account.get("username", ""))

        if _normalized_email(username) != expected:
            try:
                app.remove_account(account)
            except Exception:
                logger.warning(
                    "Could not remove an unexpected Microsoft account "
                    "from the local token cache."
                )


async def complete_authentication(
    *,
    flow: dict[str, Any],
    auth_response: dict[str, str],
) -> None:
    """
    Redeem Microsoft's authorization response and validate the fixed sender.
    """

    settings = get_settings()
    app = get_microsoft_app()

    try:
        result = app.acquire_token_by_auth_code_flow(
            auth_code_flow=flow,
            auth_response=auth_response,
        )
    except ValueError as exc:
        raise MicrosoftAuthenticationRequired(
            "Microsoft sign-in response could not be validated."
        ) from exc

    access_token = result.get("access_token")

    if not access_token:
        logger.warning(
            "Microsoft authentication failed: %s",
            result.get("error"),
        )

        raise MicrosoftAuthenticationRequired("Microsoft sign-in was not completed.")

    actual_sender = await _resolve_graph_sender(str(access_token))

    if _normalized_email(actual_sender) != _normalized_email(
        settings.microsoft_fixed_sender_email
    ):
        _remove_non_fixed_accounts()

        raise MicrosoftWrongAccountError(
            "This application can send only from "
            f"{settings.microsoft_fixed_sender_email}."
        )

    # Accessing the account confirms that the encrypted persistent cache
    # contains the signed-in sender.
    if _get_fixed_sender_account() is None:
        raise MicrosoftAuthenticationRequired(
            "Microsoft sign-in completed, but the account could not "
            "be stored in the persistent token cache."
        )


def acquire_access_token_silent() -> str:
    """
    Get a Graph access token without browser interaction.

    MSAL uses the persistent refresh token when the access token has expired.
    """

    account = _get_fixed_sender_account()

    if account is None:
        raise MicrosoftAuthenticationRequired("Microsoft sign-in is required.")

    app = get_microsoft_app()

    result = app.acquire_token_silent(
        scopes=MICROSOFT_SCOPES,
        account=account,
    )

    if not result:
        raise MicrosoftAuthenticationRequired("Microsoft sign-in is required.")

    access_token = result.get("access_token")

    if not access_token:
        logger.info(
            "Silent Microsoft token acquisition requires interaction: %s",
            result.get("error"),
        )

        raise MicrosoftAuthenticationRequired("Microsoft sign-in is required.")

    return str(access_token)


def is_authenticated() -> bool:
    """Return whether the fixed sender can obtain a token silently."""

    try:
        acquire_access_token_silent()
    except MicrosoftAuthenticationRequired:
        return False

    return True
