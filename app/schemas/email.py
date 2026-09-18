from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    field_validator,
)


class EmailPreviewRequest(BaseModel):
    """Request used to build an email preview."""

    selected_company_rows: list[int] = Field(
        min_length=1,
        max_length=100,
    )

    subject: str = Field(
        min_length=1,
        max_length=200,
    )

    content: str = Field(
        min_length=1,
        max_length=20_000,
    )

    @field_validator("selected_company_rows")
    @classmethod
    def validate_selected_rows(
        cls,
        value: list[int],
    ) -> list[int]:
        """Validate and de-duplicate Excel row IDs."""

        if any(row < 1 for row in value):
            raise ValueError(
                "Selected company rows must be positive integers."
            )

        return list(
            dict.fromkeys(value)
        )

    @field_validator("subject", "content")
    @classmethod
    def strip_text(
        cls,
        value: str,
    ) -> str:
        """Reject whitespace-only subject or content."""

        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "Value cannot be empty or whitespace."
            )

        return cleaned


class EmailSendRequest(EmailPreviewRequest):
    """Request used to send selected emails through Microsoft Graph."""


class EmailPreviewRecipient(BaseModel):
    """Resolved recipient route."""

    source_row: int
    module: str
    name: str
    third_party_group: str

    to: list[EmailStr]
    cc: list[EmailStr]


class EmailPreviewResponse(BaseModel):
    """Preview shown before sending."""

    sender: EmailStr | None = None

    subject: str
    content: str

    recipient_count: int

    recipients: list[
        EmailPreviewRecipient
    ]


class EmailSendResult(BaseModel):
    """Result for one recipient route."""

    source_row: int
    name: str

    success: bool
    detail: str


class EmailSendResponse(BaseModel):
    """Overall email send result."""

    sender: EmailStr

    total: int
    successful: int
    failed: int

    results: list[EmailSendResult]
