from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from app.routes import email as email_routes

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

    monkeypatch.setattr(
        email_routes,
        "SEND_JOB_DB_FILE",
        tmp_path / "send_jobs.sqlite3",
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

    assert body["preview_id"]
    assert body["workbook_version"]
    assert body["created_at"]

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


def test_legacy_direct_send_is_retired() -> None:
    response = client.post(
        "/email/send",
        json={
            "selected_company_rows": [2],
            "subject": "Test",
            "content": "Test email.",
        },
    )

    assert response.status_code == 410
    assert "POST /email/preview" in response.json()["detail"]
    assert "POST /mail/submit" in response.json()["detail"]
