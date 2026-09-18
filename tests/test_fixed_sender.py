import pytest

from app.services import email_service


FIXED_SENDER = "angelofarah1@outlook.com"


@pytest.mark.anyio
async def test_fixed_sender_accepts_configured_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status_code = 200
        is_success = True

        def json(self) -> dict:
            return {
                "mail": FIXED_SENDER,
                "userPrincipalName": FIXED_SENDER,
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        email_service.httpx,
        "AsyncClient",
        lambda **kwargs: FakeClient(),
    )

    sender = await email_service._get_sender_email(
        access_token="fake-token",
        expected_sender_email=FIXED_SENDER,
    )

    assert sender == FIXED_SENDER


@pytest.mark.anyio
async def test_fixed_sender_blocks_other_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status_code = 200
        is_success = True

        def json(self) -> dict:
            return {
                "mail": "someoneelse@outlook.com",
                "userPrincipalName": "someoneelse@outlook.com",
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        email_service.httpx,
        "AsyncClient",
        lambda **kwargs: FakeClient(),
    )

    with pytest.raises(
        email_service.EmailAuthenticationError,
        match="authorized to send only",
    ):
        await email_service._get_sender_email(
            access_token="fake-token",
            expected_sender_email=FIXED_SENDER,
        )
