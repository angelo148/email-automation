from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.schemas.company import CompanyRecord
from app.services.excel_service import (
    ExcelValidationError,
    load_companies_from_excel,
)


router = APIRouter(
    tags=["Web"],
)

templates = Jinja2Templates(
    directory="app/templates",
)


# Backward-compatible module-level path.
#
# Tests monkeypatch this value with an isolated workbook.
# The default still comes from centralized application settings.
COMPANIES_FILE = get_settings().companies_file


def _group_companies_by_third_party(
    companies: list[CompanyRecord],
) -> dict[str, list[CompanyRecord]]:
    """
    Group recipient routes by Third Party Group.

    Group order follows the order in the Excel workbook.
    Individual rows remain separate so their To/CC
    configuration is never merged.
    """

    grouped: dict[str, list[CompanyRecord]] = defaultdict(list)

    for company in companies:
        grouped[company.third_party_group].append(
            company
        )

    return dict(grouped)


@router.get(
    "/",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
)
async def home(
    request: Request,
) -> HTMLResponse:
    """Render the email composition interface."""

    try:
        companies = load_companies_from_excel(
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

    grouped_companies = (
        _group_companies_by_third_party(
            companies
        )
    )

    sendable_count = sum(
        1
        for company in companies
        if company.can_email
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "grouped_companies": grouped_companies,
            "sendable_count": sendable_count,
        },
    )