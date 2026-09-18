from fastapi import APIRouter, status

from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter(
    tags=["Health"],
)


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
)
async def health_check() -> HealthResponse:
    """Return application health information."""
    settings = get_settings()

    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )