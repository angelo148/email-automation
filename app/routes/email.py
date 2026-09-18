from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    status,
)

from app.core.config import get_settings
from app.schemas.email import (
    EmailPreviewRequest,
    EmailPreviewResponse,
    EmailSendRequest,
    EmailSendResponse,
)
from app.services.email_service import (
    EmailAuthenticationError,
    EmailPreviewError,
    EmailSendError,
    build_email_preview,
    send_selected_emails,
)
from app.services.excel_service import (
    ExcelValidationError,
    load_companies_from_excel,
)
from app.services.microsoft_auth_service import (
    MicrosoftAuthConfigurationError,
    MicrosoftAuthenticationRequired,
    acquire_access_token_silent,
)


router = APIRouter(
    prefix="/email",
    tags=["Email"],
)

# Keep this module-level variable because the current tests monkeypatch it.
COMPANIES_FILE = get_settings().companies_file


def _extract_bearer_token(
    authorization: str | None,
) -> str:
    """Extract the existing frontend bearer token safely."""

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Microsoft sign-in is required.",
        )

    scheme, _, token = authorization.partition(
        " "
    )

    if (
        scheme.casefold() != "bearer"
        or not token.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Microsoft authorization header.",
        )

    return token.strip()


def _load_companies():
    try:
        return load_companies_from_excel(
            COMPANIES_FILE
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Third-party Excel file was not found.",
        ) from exc

    except ExcelValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


async def _send_with_token(
    *,
    request: EmailSendRequest,
    access_token: str,
) -> EmailSendResponse:
    settings = get_settings()
    companies = _load_companies()

    try:
        return await send_selected_emails(
            request=request,
            companies=companies,
            access_token=access_token,
            fixed_sender_email=(
                settings.microsoft_fixed_sender_email
            ),
        )

    except EmailPreviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except EmailAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    except EmailSendError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post(
    "/preview",
    response_model=EmailPreviewResponse,
)
async def preview_email(
    request: EmailPreviewRequest,
) -> EmailPreviewResponse:
    """Preview resolved recipients without sending."""

    settings = get_settings()
    companies = _load_companies()

    try:
        return build_email_preview(
            request=request,
            companies=companies,
            sender_email=(
                settings.microsoft_fixed_sender_email
            ),
        )

    except EmailPreviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/send",
    response_model=EmailSendResponse,
    status_code=status.HTTP_200_OK,
)
async def send_email(
    request: EmailSendRequest,
    authorization: str | None = Header(
        default=None
    ),
) -> EmailSendResponse:
    """
    Existing bearer-token endpoint retained for backward compatibility/tests.
    """

    access_token = _extract_bearer_token(
        authorization
    )

    return await _send_with_token(
        request=request,
        access_token=access_token,
    )


@router.post(
    "/send-persistent",
    response_model=EmailSendResponse,
    status_code=status.HTTP_200_OK,
)
async def send_email_with_persistent_session(
    request: EmailSendRequest,
) -> EmailSendResponse:
    """
    Send using the encrypted backend Microsoft token cache.

    No browser bearer token is required.
    """

    try:
        access_token = (
            acquire_access_token_silent()
        )

    except MicrosoftAuthenticationRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Microsoft sign-in is required.",
        ) from exc

    except MicrosoftAuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Microsoft authentication is not configured.",
        ) from exc

    return await _send_with_token(
        request=request,
        access_token=access_token,
    )
