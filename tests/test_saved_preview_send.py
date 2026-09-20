import asyncio
from pathlib import Path

import pytest

from app.schemas.email import (
    EmailPreviewRecipient,
    EmailRouteStatus,
)
from app.services import email_service
from app.services.send_job_service import (
    claim_send_job,
    save_preview,
)

FIXED_SENDER = "angelofarah1@outlook.com"


def create_saved_preview(
    database_path: Path,
):
    return save_preview(
        database_path=database_path,
        sender=FIXED_SENDER,
        subject="Test subject",
        content="Test content",
        workbook_version="test-workbook-version",
        recipients=[
            EmailPreviewRecipient(
                source_row=2,
                module="Module A",
                name="Company A",
                third_party_group="Group A",
                to=["company-a@example.com"],
                cc=[],
            ),
            EmailPreviewRecipient(
                source_row=3,
                module="Module B",
                name="Company B",
                third_party_group="Group B",
                to=["company-b@example.com"],
                cc=[],
            ),
            EmailPreviewRecipient(
                source_row=4,
                module="Module C",
                name="Company C",
                third_party_group="Group C",
                to=["company-c@example.com"],
                cc=[],
            ),
        ],
    )


def test_saved_preview_send_does_not_resend_accepted_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "send_jobs.sqlite3"

    preview = create_saved_preview(database_path)

    claim = claim_send_job(
        database_path=database_path,
        preview_id=preview.preview_id,
    )

    sent_to: list[str] = []

    async def fake_sender(
        access_token: str,
        expected_sender_email: str,
    ) -> str:
        assert access_token == "fake-token"
        assert expected_sender_email == FIXED_SENDER

        return FIXED_SENDER

    async def fake_send(
        **kwargs,
    ) -> None:
        sent_to.append(kwargs["to_addresses"][0])

    monkeypatch.setattr(
        email_service,
        "_get_sender_email",
        fake_sender,
    )

    monkeypatch.setattr(
        email_service,
        "_send_graph_email",
        fake_send,
    )

    first_result = asyncio.run(
        email_service.send_saved_preview_job(
            preview=preview,
            job_id=claim.job_id,
            database_path=database_path,
            access_token="fake-token",
            fixed_sender_email=FIXED_SENDER,
        )
    )

    assert first_result.accepted == 3
    assert first_result.pending == 0

    assert sent_to == [
        "company-a@example.com",
        "company-b@example.com",
        "company-c@example.com",
    ]

    second_result = asyncio.run(
        email_service.send_saved_preview_job(
            preview=preview,
            job_id=claim.job_id,
            database_path=database_path,
            access_token="fake-token",
            fixed_sender_email=FIXED_SENDER,
        )
    )

    assert second_result.accepted == 3

    assert sent_to == [
        "company-a@example.com",
        "company-b@example.com",
        "company-c@example.com",
    ]


def test_authentication_failure_preserves_partial_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "send_jobs.sqlite3"

    preview = create_saved_preview(database_path)

    claim = claim_send_job(
        database_path=database_path,
        preview_id=preview.preview_id,
    )

    send_count = 0

    async def fake_sender(
        access_token: str,
        expected_sender_email: str,
    ) -> str:
        return FIXED_SENDER

    async def fake_send(
        **kwargs,
    ) -> None:
        nonlocal send_count

        send_count += 1

        if send_count == 2:
            raise (
                email_service.EmailAuthenticationError("Microsoft sign-in is required.")
            )

    monkeypatch.setattr(
        email_service,
        "_get_sender_email",
        fake_sender,
    )

    monkeypatch.setattr(
        email_service,
        "_send_graph_email",
        fake_send,
    )

    first_result = asyncio.run(
        email_service.send_saved_preview_job(
            preview=preview,
            job_id=claim.job_id,
            database_path=database_path,
            access_token="fake-token",
            fixed_sender_email=FIXED_SENDER,
        )
    )

    assert first_result.accepted == 1

    assert first_result.authentication_required == 2

    assert first_result.results[0].status == EmailRouteStatus.ACCEPTED

    assert first_result.results[1].status == EmailRouteStatus.AUTHENTICATION_REQUIRED

    assert first_result.results[2].status == EmailRouteStatus.AUTHENTICATION_REQUIRED

    resumed_to: list[str] = []

    async def fake_resume_send(
        **kwargs,
    ) -> None:
        resumed_to.append(kwargs["to_addresses"][0])

    monkeypatch.setattr(
        email_service,
        "_send_graph_email",
        fake_resume_send,
    )

    resumed_result = asyncio.run(
        email_service.send_saved_preview_job(
            preview=preview,
            job_id=claim.job_id,
            database_path=database_path,
            access_token="new-token",
            fixed_sender_email=FIXED_SENDER,
        )
    )

    assert resumed_result.accepted == 3

    assert resumed_result.authentication_required == 0

    assert resumed_to == [
        "company-b@example.com",
        "company-c@example.com",
    ]
