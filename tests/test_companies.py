from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from app.routes import companies as companies_routes

client = TestClient(app)


def create_companies_test_workbook(
    file_path: Path,
) -> None:
    """Create an isolated workbook for API tests."""

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
            None,
            "Alfa",
            "Alfa",
            "first@alfa.com\nsecond@alfa.com",
            "manager@alfa.com",
        ]
    )

    worksheet.append(
        [
            None,
            "Likecard",
            "Likecard",
            "Contact support on their website",
            None,
        ]
    )

    workbook.save(file_path)
    workbook.close()


@pytest.fixture
def companies_excel_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Replace the production Excel path with a temporary test workbook."""

    file_path = tmp_path / "companies.xlsx"

    create_companies_test_workbook(file_path)

    monkeypatch.setattr(
        companies_routes,
        "COMPANIES_FILE",
        file_path,
    )

    return file_path


def test_get_companies_returns_companies(
    companies_excel_file: Path,
) -> None:
    response = client.get("/companies")

    assert response.status_code == 200

    companies = response.json()

    assert len(companies) == 3

    assert companies[0] == {
        "module": "Vouchers",
        "name": "OMTs",
        "third_party_group": "OMT",
        "to": [
            "omt@example.com",
        ],
        "cc": [
            "manager@omt.com",
        ],
        "can_email": True,
        "unavailable_reason": None,
        "source_row": 2,
    }

    assert companies[1] == {
        "module": "Vouchers",
        "name": "Alfa",
        "third_party_group": "Alfa",
        "to": [
            "first@alfa.com",
            "second@alfa.com",
        ],
        "cc": [
            "manager@alfa.com",
        ],
        "can_email": True,
        "unavailable_reason": None,
        "source_row": 3,
    }

    assert companies[2] == {
        "module": "Vouchers",
        "name": "Likecard",
        "third_party_group": "Likecard",
        "to": [],
        "cc": [],
        "can_email": False,
        "unavailable_reason": ("Contact support on their website"),
        "source_row": 4,
    }
