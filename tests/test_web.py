import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from app.routes import web as web_routes

client = TestClient(app)


def create_ui_test_workbook(
    file_path: Path,
) -> None:
    """Create an isolated workbook for web UI tests."""

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
            None,
        ]
    )

    worksheet.append(
        [
            None,
            "Alfa",
            "Alfa",
            "alfa@example.com",
            None,
        ]
    )

    worksheet.append(
        [
            None,
            "Touch",
            "Touch",
            "touch@example.com",
            None,
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

    worksheet.append(
        [
            None,
            "Reloadly",
            "Reloadly",
            None,
            None,
        ]
    )

    workbook.save(file_path)
    workbook.close()


@pytest.fixture
def web_excel_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Replace the production Excel path for web tests."""

    file_path = tmp_path / "companies.xlsx"

    create_ui_test_workbook(file_path)

    monkeypatch.setattr(
        web_routes,
        "COMPANIES_FILE",
        file_path,
    )

    return file_path


def test_home_page_loads_multiselect(
    web_excel_file: Path,
) -> None:
    response = client.get("/")

    assert response.status_code == 200

    html = response.text

    assert "AI Email Automation" in html
    assert "Search by third party, group, or module..." in html
    assert "Select All" in html
    assert "Unselect All" in html


def test_companies_are_rendered(
    web_excel_file: Path,
) -> None:
    response = client.get("/")

    assert response.status_code == 200

    html = response.text

    assert "OMTs" in html
    assert "Alfa" in html
    assert "Touch" in html
    assert "Likecard" in html
    assert "Reloadly" in html


def test_third_party_groups_are_rendered(
    web_excel_file: Path,
) -> None:
    response = client.get("/")

    assert response.status_code == 200

    html = response.text

    assert 'data-group-name="OMT"' in html
    assert 'data-group-name="Alfa"' in html
    assert 'data-group-name="Touch"' in html


def test_sendable_companies_start_selected(
    web_excel_file: Path,
) -> None:
    response = client.get("/")

    assert response.status_code == 200

    html = response.text

    sendable_options = re.findall(
        r"<button[^>]*"
        r"data-company-option[^>]*"
        r'data-can-email="true"[^>]*'
        r'data-selected="true"[^>]*>',
        html,
        flags=re.DOTALL,
    )

    assert len(sendable_options) == 3


def test_unavailable_companies_are_disabled(
    web_excel_file: Path,
) -> None:
    response = client.get("/")

    assert response.status_code == 200

    html = response.text

    assert html.count('data-can-email="false"') == 2

    assert "Contact support on their website" in html
    assert "No email address configured." in html
