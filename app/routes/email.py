from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from app.core.config import get_settings
from app.schemas.email import (
    EmailJobResponse,
    EmailJobStatus,
    EmailPreviewRequest,
    EmailSendByPreviewRequest,
    SavedEmailPreview,
)
from app.services.email_service import (
    EmailPreviewError,
    build_email_preview,
    send_saved_preview_job,
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
from app.services.send_job_service import (
    PreviewNotFoundError,
    calculate_workbook_version,
    claim_send_job,
    get_preview,
    get_send_job,
    get_send_job_for_preview,
    save_preview,
)

router = APIRouter(
    prefix="/email",
    tags=["Email"],
)

# Keep this module-level variable because the current tests monkeypatch it.
COMPANIES_FILE = get_settings().companies_file
SEND_JOB_DB_FILE = get_settings().send_job_db_file


@router.post(
    "/preview",
    response_model=SavedEmailPreview,
)
async def preview_email(
    request: EmailPreviewRequest,
) -> SavedEmailPreview:
    """Create and persist an immutable email preview."""

    try:
        workbook_version_before = calculate_workbook_version(COMPANIES_FILE)

        companies = load_companies_from_excel(COMPANIES_FILE)

        workbook_version_after = calculate_workbook_version(COMPANIES_FILE)

        if workbook_version_before != workbook_version_after:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Recipient workbook changed while "
                    "the preview was being created. "
                    "Please preview the email again."
                ),
            )

        settings = get_settings()

        preview = build_email_preview(
            request=request,
            companies=companies,
            sender_email=(settings.microsoft_fixed_sender_email),
        )

        return save_preview(
            database_path=SEND_JOB_DB_FILE,
            sender=(str(preview.sender) if preview.sender else None),
            subject=preview.subject,
            content=preview.content,
            recipients=preview.recipients,
            workbook_version=(workbook_version_after),
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=("Third-party Excel file " "was not found."),
        ) from exc

    except ExcelValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    except EmailPreviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/send",
    status_code=status.HTTP_410_GONE,
)
async def send_email_legacy() -> dict[str, str]:
    """
    Retired direct-send endpoint. Use the preview and persistent queue flow.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Direct sending has been retired. Create a preview with "
            "POST /email/preview, then queue it with POST /mail/submit."
        ),
    )


@router.post(
    "/send-persistent",
    response_model=EmailJobResponse,
    status_code=status.HTTP_200_OK,
)
async def send_email_with_persistent_session(
    request: EmailSendByPreviewRequest,
) -> EmailJobResponse:
    """
    Send the exact immutable preview previously reviewed by the user.

    New sends verify that the workbook has not changed since preview.
    Repeated requests return the existing job instead of resending.
    Authentication-interrupted jobs may resume only their unfinished routes.
    """

    try:
        preview = get_preview(
            database_path=SEND_JOB_DB_FILE,
            preview_id=request.preview_id,
        )

    except PreviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "The email preview no longer exists. " "Please create a new preview."
            ),
        ) from exc

    existing_job = get_send_job_for_preview(
        database_path=SEND_JOB_DB_FILE,
        preview_id=request.preview_id,
    )

    if (
        existing_job is not None
        and existing_job.status != EmailJobStatus.AUTHENTICATION_REQUIRED
    ):
        return existing_job

    if existing_job is None:
        try:
            current_workbook_version = calculate_workbook_version(COMPANIES_FILE)

        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=(status.HTTP_500_INTERNAL_SERVER_ERROR),
                detail=("Third-party Excel file " "was not found."),
            ) from exc

        if current_workbook_version != preview.workbook_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Recipient data changed after "
                    "this preview was created. "
                    "Please review the email again."
                ),
            )

    try:
        access_token = acquire_access_token_silent()

    except MicrosoftAuthenticationRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Microsoft sign-in is required.",
        ) from exc

    except MicrosoftAuthConfigurationError as exc:
        raise HTTPException(
            status_code=(status.HTTP_500_INTERNAL_SERVER_ERROR),
            detail=("Microsoft authentication " "is not configured."),
        ) from exc

    try:
        claim = claim_send_job(
            database_path=SEND_JOB_DB_FILE,
            preview_id=request.preview_id,
        )

    except PreviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "The email preview no longer exists. " "Please create a new preview."
            ),
        ) from exc

    if not claim.claimed:
        return get_send_job(
            database_path=SEND_JOB_DB_FILE,
            job_id=claim.job_id,
        )

    settings = get_settings()

    job = await send_saved_preview_job(
        preview=preview,
        job_id=claim.job_id,
        database_path=SEND_JOB_DB_FILE,
        access_token=access_token,
        fixed_sender_email=(settings.microsoft_fixed_sender_email),
    )

    if job.status == EmailJobStatus.AUTHENTICATION_REQUIRED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Microsoft sign-in is required.",
        )

    return job
