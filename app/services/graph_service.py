import httpx

from app.core.logging import get_logger


logger = get_logger(__name__)


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_TIMEOUT_SECONDS = 20.0


class GraphAuthenticationError(RuntimeError):
    """Raised when Microsoft Graph rejects authentication or authorization."""


class GraphRequestError(RuntimeError):
    """Raised when a Microsoft Graph request cannot be completed."""


def _authorization_headers(
    access_token: str,
) -> dict[str, str]:
    """Build Microsoft Graph authorization headers."""

    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _build_message_payload(
    *,
    subject: str,
    content: str,
    to_addresses: list[str],
    cc_addresses: list[str],
) -> dict:
    """Build one independent Microsoft Graph sendMail payload."""

    if not to_addresses:
        raise GraphRequestError(
            "Cannot send an email without at least one To recipient."
        )

    message: dict = {
        "subject": subject,
        "body": {
            "contentType": "Text",
            "content": content,
        },
        "toRecipients": [
            {
                "emailAddress": {
                    "address": address,
                }
            }
            for address in to_addresses
        ],
    }

    if cc_addresses:
        message["ccRecipients"] = [
            {
                "emailAddress": {
                    "address": address,
                }
            }
            for address in cc_addresses
        ]

    return {
        "message": message,
        "saveToSentItems": True,
    }


async def get_sender_email(
    *,
    access_token: str,
    expected_sender_email: str,
) -> str:
    """
    Resolve and validate the signed-in Microsoft sender.

    The access token is used only for the request and is never logged.
    """

    headers = _authorization_headers(
        access_token
    )

    async with httpx.AsyncClient(
        timeout=GRAPH_TIMEOUT_SECONDS,
    ) as client:
        try:
            response = await client.get(
                f"{GRAPH_BASE_URL}/me",
                headers=headers,
                params={
                    "$select": (
                        "mail,"
                        "userPrincipalName"
                    ),
                },
            )
        except httpx.RequestError as exc:
            logger.error(
                "Could not reach Microsoft Graph while resolving sender."
            )

            raise GraphRequestError(
                "Could not connect to Microsoft Graph."
            ) from exc

    if response.status_code in {
        401,
        403,
    }:
        raise GraphAuthenticationError(
            "Microsoft sign-in is no longer valid. "
            "Sign in again and retry."
        )

    if not response.is_success:
        logger.error(
            "Microsoft Graph sender lookup failed with HTTP %d.",
            response.status_code,
        )

        raise GraphRequestError(
            "Microsoft Graph could not resolve the signed-in sender."
        )

    data = response.json()

    sender_email = (
        data.get("mail")
        or data.get("userPrincipalName")
    )

    if (
        not isinstance(sender_email, str)
        or "@" not in sender_email
    ):
        raise GraphAuthenticationError(
            "Microsoft did not return a valid sender email address."
        )

    sender_email = sender_email.strip()
    expected_sender_email = (
        expected_sender_email.strip()
    )

    if (
        sender_email.casefold()
        != expected_sender_email.casefold()
    ):
        logger.warning(
            "Blocked Microsoft account '%s'; fixed sender is '%s'.",
            sender_email,
            expected_sender_email,
        )

        raise GraphAuthenticationError(
            "This application is authorized to send only from "
            f"{expected_sender_email}."
        )

    return sender_email


async def send_email(
    *,
    access_token: str,
    subject: str,
    content: str,
    to_addresses: list[str],
    cc_addresses: list[str],
) -> None:
    """Send one completely separate email through Microsoft Graph."""

    payload = _build_message_payload(
        subject=subject,
        content=content,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
    )

    headers = _authorization_headers(
        access_token
    )

    headers["Content-Type"] = (
        "application/json"
    )

    async with httpx.AsyncClient(
        timeout=GRAPH_TIMEOUT_SECONDS,
    ) as client:
        try:
            response = await client.post(
                f"{GRAPH_BASE_URL}/me/sendMail",
                headers=headers,
                json=payload,
            )
        except httpx.RequestError as exc:
            logger.error(
                "Could not reach Microsoft Graph while sending email."
            )

            raise GraphRequestError(
                "Could not connect to Microsoft Graph."
            ) from exc

    if response.status_code in {
        401,
        403,
    }:
        raise GraphAuthenticationError(
            "Microsoft authorization was rejected. "
            "Sign in again and retry."
        )

    if response.status_code != 202:
        logger.error(
            "Microsoft Graph sendMail failed with HTTP %d.",
            response.status_code,
        )

        raise GraphRequestError(
            "Microsoft Graph rejected the email."
        )