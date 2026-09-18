from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from app.routes import email as email_routes
from app.services import email_service

client = TestClient(app)

FIXED_SENDER = "angelofarah1@outlook.com"


def create_email_test_workbook(
    file_path: Path,
) -> None:
    """Create a small Excel workbook used only by email route tests."""

    workbook = Workbook()
    worksheet = workbook.active

    worksheet.append(
        [
            "Module",
            "Third Party",
            "Third Party Group",
            "Email To",
            "Email CC",
        ]
    )

    worksheet.append(
        [
            "Vouchers",
            "OMTs",
            "OMT",
            "omt@example.com",
            "manager@omt.com",
        ]
    )

    worksheet.append(
        [
            "MTO",
            "OMT",
            "OMT",
            "mto@example.com",
            "operations@omt.com",
        ]
    )

    worksheet.append(
        [
            "Vouchers",
            "Likecard",
            "Likecard",
            "Contact support on their website",
            None,
        ]
    )

    workbook.save(file_path)
    workbook.close()


@pytest.fixture
def email_excel_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Point the email routes at an isolated test workbook."""

    file_path = tmp_path / "companies.xlsx"

    create_email_test_workbook(file_path)

    monkeypatch.setattr(
        email_routes,
        "COMPANIES_FILE",
        file_path,
    )

    return file_path


def test_preview_resolves_selected_recipients(
    email_excel_file: Path,
) -> None:
    response = client.post(
        "/email/preview",
        json={
            "selected_company_rows": [
                2,
                3,
            ],
            "subject": "Ticket Support",
            "content": "Please investigate this issue.",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["sender"] == FIXED_SENDER
    assert body["subject"] == "Ticket Support"
    assert body["content"] == "Please investigate this issue."
    assert body["recipient_count"] == 2

    assert body["recipients"][0] == {
        "source_row": 2,
        "module": "Vouchers",
        "name": "OMTs",
        "third_party_group": "OMT",
        "to": ["omt@example.com"],
        "cc": ["manager@omt.com"],
    }

    assert body["recipients"][1] == {
        "source_row": 3,
        "module": "MTO",
        "name": "OMT",
        "third_party_group": "OMT",
        "to": ["mto@example.com"],
        "cc": ["operations@omt.com"],
    }


def test_preview_rejects_unavailable_recipient(
    email_excel_file: Path,
) -> None:
    response = client.post(
        "/email/preview",
        json={
            "selected_company_rows": [4],
            "subject": "Test",
            "content": "Test email.",
        },
    )

    assert response.status_code == 400
    assert "cannot receive email" in response.json()["detail"]


def test_preview_rejects_unknown_row(
    email_excel_file: Path,
) -> None:
    response = client.post(
        "/email/preview",
        json={
            "selected_company_rows": [999],
            "subject": "Test",
            "content": "Test email.",
        },
    )

    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]


def test_preview_rejects_empty_subject(
    email_excel_file: Path,
) -> None:
    response = client.post(
        "/email/preview",
        json={
            "selected_company_rows": [2],
            "subject": "   ",
            "content": "Test email.",
        },
    )

    assert response.status_code == 422


def test_preview_removes_duplicate_rows(
    email_excel_file: Path,
) -> None:
    response = client.post(
        "/email/preview",
        json={
            "selected_company_rows": [
                2,
                2,
                3,
            ],
            "subject": "Test",
            "content": "Test email.",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["sender"] == FIXED_SENDER
    assert body["recipient_count"] == 2
    assert [recipient["source_row"] for recipient in body["recipients"]] == [2, 3]


def test_send_requires_bearer_token(
    email_excel_file: Path,
) -> None:
    response = client.post(
        "/email/send",
        json={
            "selected_company_rows": [2],
            "subject": "Test",
            "content": "Test email.",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == ("Microsoft sign-in is required.")


def test_send_succeeds_for_all_recipients(
    email_excel_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_routes: list[tuple[list[str], list[str]]] = []

    async def fake_sender(
        access_token: str,
        expected_sender_email: str,
    ) -> str:
        assert access_token == "fake-token"
        assert expected_sender_email == FIXED_SENDER

        return FIXED_SENDER

    async def fake_send(
        *,
        access_token: str,
        subject: str,
        content: str,
        to_addresses: list[str],
        cc_addresses: list[str],
    ) -> None:
        assert access_token == "fake-token"
        assert subject == "Ticket Support"
        assert content == "Please investigate this issue."

        sent_routes.append(
            (
                to_addresses,
                cc_addresses,
            )
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

    response = client.post(
        "/email/send",
        headers={
            "Authorization": "Bearer fake-token",
        },
        json={
            "selected_company_rows": [
                2,
                3,
            ],
            "subject": "Ticket Support",
            "content": "Please investigate this issue.",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["sender"] == FIXED_SENDER
    assert body["total"] == 2
    assert body["successful"] == 2
    assert body["failed"] == 0

    assert sent_routes == [
        (
            ["omt@example.com"],
            ["manager@omt.com"],
        ),
        (
            ["mto@example.com"],
            ["operations@omt.com"],
        ),
    ]


def test_send_records_per_recipient_failure(
    email_excel_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        raise email_service.EmailSendError("Simulated Graph send failure.")

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

    response = client.post(
        "/email/send",
        headers={
            "Authorization": "Bearer fake-token",
        },
        json={
            "selected_company_rows": [2],
            "subject": "Test",
            "content": "Test email.",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["sender"] == FIXED_SENDER
    assert body["total"] == 1
    assert body["successful"] == 0
    assert body["failed"] == 1
    assert body["results"][0]["success"] is False
    assert body["results"][0]["detail"] == "Simulated Graph send failure."


def test_send_rejects_invalid_microsoft_session(
    email_excel_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sender(
        access_token: str,
        expected_sender_email: str,
    ) -> str:
        assert access_token == "expired-token"
        assert expected_sender_email == FIXED_SENDER

        raise email_service.EmailAuthenticationError(
            "Microsoft sign-in is no longer valid."
        )

    monkeypatch.setattr(
        email_service,
        "_get_sender_email",
        fake_sender,
    )

    response = client.post(
        "/email/send",
        headers={
            "Authorization": "Bearer expired-token",
        },
        json={
            "selected_company_rows": [2],
            "subject": "Test",
            "content": "Test email.",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == ("Microsoft sign-in is no longer valid.")
