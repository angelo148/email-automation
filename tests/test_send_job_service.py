from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.schemas.email import (
    EmailPreviewRecipient,
    EmailRouteStatus,
)
from app.services.send_job_service import (
    claim_send_job,
    get_preview,
    get_send_job,
    record_route_status,
    save_preview,
)


def create_preview(
    database_path: Path,
):
    return save_preview(
        database_path=database_path,
        sender="angelofarah1@outlook.com",
        subject="Test subject",
        content="Test content",
        workbook_version="test-workbook-version",
        recipients=[
            EmailPreviewRecipient(
                source_row=2,
                module="Test",
                name="Company A",
                third_party_group="Group A",
                to=["company-a@example.com"],
                cc=[],
            )
        ],
    )


def test_preview_is_persisted(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "send_jobs.sqlite3"

    saved = create_preview(database_path)

    loaded = get_preview(
        database_path=database_path,
        preview_id=saved.preview_id,
    )

    assert loaded.preview_id == saved.preview_id
    assert loaded.subject == "Test subject"
    assert loaded.recipient_count == 1
    assert str(loaded.recipients[0].to[0]) == "company-a@example.com"


def test_repeated_claim_returns_same_job(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "send_jobs.sqlite3"

    preview = create_preview(database_path)

    first = claim_send_job(
        database_path=database_path,
        preview_id=preview.preview_id,
    )

    second = claim_send_job(
        database_path=database_path,
        preview_id=preview.preview_id,
    )

    assert first.claimed is True
    assert second.claimed is False

    assert first.job_id == second.job_id


def test_route_result_is_persisted(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "send_jobs.sqlite3"

    preview = create_preview(database_path)

    claim = claim_send_job(
        database_path=database_path,
        preview_id=preview.preview_id,
    )

    record_route_status(
        database_path=database_path,
        job_id=claim.job_id,
        route_index=0,
        status=EmailRouteStatus.ACCEPTED,
        detail="Accepted by Microsoft Graph.",
    )

    job = get_send_job(
        database_path=database_path,
        job_id=claim.job_id,
    )

    assert job.accepted == 1
    assert job.pending == 0

    assert job.results[0].status == EmailRouteStatus.ACCEPTED


def test_concurrent_claim_creates_one_job(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "send_jobs.sqlite3"

    preview = create_preview(database_path)

    def claim():
        return claim_send_job(
            database_path=database_path,
            preview_id=preview.preview_id,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        claims = list(
            executor.map(
                lambda _: claim(),
                range(4),
            )
        )

    job_ids = {claim.job_id for claim in claims}

    claimed_count = sum(claim.claimed for claim in claims)

    assert len(job_ids) == 1
    assert claimed_count == 1
