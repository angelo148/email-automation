from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.schemas.company import CompanyResponse
from app.services.excel_service import (
    ExcelValidationError,
    load_companies_from_excel,
)


router = APIRouter(
    prefix="/companies",
    tags=["Companies"],
)


# Backward-compatible module-level path.
#
# Tests monkeypatch this value with an isolated workbook.
# The default still comes from centralized application settings.
COMPANIES_FILE = get_settings().companies_file


@router.get(
    "",
    response_model=list[CompanyResponse],
    status_code=status.HTTP_200_OK,
)
async def get_companies() -> list[CompanyResponse]:
    """Return all third-party recipient configurations."""

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

    return [
        CompanyResponse(
            module=company.module,
            name=company.name,
            third_party_group=company.third_party_group,
            to=company.to,
            cc=company.cc,
            can_email=company.can_email,
            unavailable_reason=company.unavailable_reason,
            source_row=company.source_row,
        )
        for company in companies
    ]