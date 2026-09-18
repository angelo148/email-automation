import httpx

from app.core.logging import get_logger
from app.schemas.company import CompanyRecord
from app.schemas.email import (
    EmailPreviewRecipient,
    EmailPreviewRequest,
    EmailPreviewResponse,
    EmailSendRequest,
    EmailSendResponse,
    EmailSendResult,
)
from app.services import graph_service


logger = get_logger(__name__)


class EmailPreviewError(ValueError):
    """Raised when an email preview cannot be created."""


class EmailConfigurationError(RuntimeError):
    """
    Backward-compatible configuration error.

    Kept because the application's shared exception layer imports this
    exception.
    """


class EmailAuthenticationError(RuntimeError):
    """Raised when Microsoft rejects or cannot validate authentication."""


class EmailSendError(RuntimeError):
    """Raised when an email cannot be sent."""


def build_email_preview(
    request: EmailPreviewRequest,
    companies: list[CompanyRecord],
    sender_email: str | None = None,
) -> EmailPreviewResponse:
    """
    Resolve selected Excel rows into validated recipient routes.

    Recipient addresses are always loaded from the server-side Excel file.
    The frontend is never trusted to provide To or CC addresses.
    """

    logger.debug(
        "Creating email preview for %d selected route(s).",
        len(request.selected_company_rows),
    )

    companies_by_row = {
        company.source_row: company
        for company in companies
    }

    recipients: list[EmailPreviewRecipient] = []

    for source_row in request.selected_company_rows:
        company = companies_by_row.get(
            source_row
        )

        if company is None:
            logger.warning(
                "Preview rejected because Excel row %d does not exist.",
                source_row,
            )

            raise EmailPreviewError(
                f"Selected recipient row {source_row} does not exist."
            )

        if not company.can_email:
            logger.warning(
                "Preview rejected because route '%s' cannot receive email.",
                company.name,
            )

            raise EmailPreviewError(
                f"{company.name} cannot receive email: "
                f"{company.unavailable_reason}"
            )

        recipients.append(
            EmailPreviewRecipient(
                source_row=company.source_row,
                module=company.module,
                name=company.name,
                third_party_group=company.third_party_group,
                to=company.to,
                cc=company.cc,
            )
        )

    if not recipients:
        logger.warning(
            "Preview rejected because no recipient routes were selected."
        )

        raise EmailPreviewError(
            "At least one recipient must be selected."
        )

    return EmailPreviewResponse(
        sender=sender_email,
        subject=request.subject,
        content=request.content,
        recipient_count=len(recipients),
        recipients=recipients,
    )


async def _get_sender_email(
    access_token: str,
    expected_sender_email: str,
) -> str:
    """
    Resolve and validate the signed-in Microsoft sender.

    This compatibility wrapper keeps Graph-specific HTTP logic out of the
    email business service.
    """

    try:
        return await graph_service.get_sender_email(
            access_token=access_token,
            expected_sender_email=expected_sender_email,
        )

    except graph_service.GraphAuthenticationError as exc:
        raise EmailAuthenticationError(
            str(exc)
        ) from exc

    except graph_service.GraphRequestError as exc:
        raise EmailSendError(
            str(exc)
        ) from exc


async def _send_graph_email(
    *,
    access_token: str,
    subject: str,
    content: str,
    to_addresses: list[str],
    cc_addresses: list[str],
) -> None:
    """
    Send one independent email through the Microsoft Graph service.

    This wrapper is intentionally retained for compatibility with existing
    tests and application code.
    """

    try:
        await graph_service.send_email(
            access_token=access_token,
            subject=subject,
            content=content,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
        )

    except graph_service.GraphAuthenticationError as exc:
        raise EmailAuthenticationError(
            str(exc)
        ) from exc

    except graph_service.GraphRequestError as exc:
        raise EmailSendError(
            str(exc)
        ) from exc


async def send_selected_emails(
    *,
    request: EmailSendRequest,
    companies: list[CompanyRecord],
    access_token: str,
    fixed_sender_email: str,
) -> EmailSendResponse:
    """
    Send one independent Microsoft Graph email per selected Excel route.

    To and CC addresses always come from the trusted server-side Excel
    workbook. The Microsoft access token is request-scoped and is not stored.
    """

    sender_email = await _get_sender_email(
        access_token=access_token,
        expected_sender_email=fixed_sender_email,
    )

    preview = build_email_preview(
        request=request,
        companies=companies,
        sender_email=sender_email,
    )

    logger.debug(
        "Starting Microsoft Graph send for %d route(s).",
        preview.recipient_count,
    )

    results: list[EmailSendResult] = []

    for recipient in preview.recipients:
        to_addresses = [
            str(address)
            for address in recipient.to
        ]

        cc_addresses = [
            str(address)
            for address in recipient.cc
        ]

        try:
            await _send_graph_email(
                access_token=access_token,
                subject=preview.subject,
                content=preview.content,
                to_addresses=to_addresses,
                cc_addresses=cc_addresses,
            )

        except EmailAuthenticationError:
            raise

        except EmailSendError as exc:
            logger.error(
                "Email failed for route '%s' (Excel row %d).",
                recipient.name,
                recipient.source_row,
            )

            results.append(
                EmailSendResult(
                    source_row=recipient.source_row,
                    name=recipient.name,
                    success=False,
                    detail=str(exc),
                )
            )

            continue

        results.append(
            EmailSendResult(
                source_row=recipient.source_row,
                name=recipient.name,
                success=True,
                detail="Email accepted by Microsoft Graph.",
            )
        )

    successful = sum(
        1
        for result in results
        if result.success
    )

    failed = (
        len(results)
        - successful
    )

    return EmailSendResponse(
        sender=sender_email,
        total=len(results),
        successful=successful,
        failed=failed,
        results=results,
    )