from pydantic import BaseModel, EmailStr, Field, model_validator


class CompanyRecord(BaseModel):
    """Validated third-party recipient loaded from Excel."""

    module: str = Field(min_length=1)
    name: str = Field(min_length=1)
    third_party_group: str = Field(min_length=1)

    to: list[EmailStr] = Field(default_factory=list)
    cc: list[EmailStr] = Field(default_factory=list)

    can_email: bool
    unavailable_reason: str | None = None

    source_row: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_delivery_state(self) -> "CompanyRecord":
        """Validate that the delivery state is internally consistent."""

        if self.can_email and not self.to:
            raise ValueError(
                "A sendable third party must have at least one To address."
            )

        if not self.can_email and self.to:
            raise ValueError(
                "A non-sendable third party cannot contain To addresses."
            )

        if not self.can_email and not self.unavailable_reason:
            raise ValueError(
                "A non-sendable third party must have an unavailable reason."
            )

        return self


class CompanyResponse(BaseModel):
    """Third-party recipient returned by the API."""

    module: str
    name: str
    third_party_group: str

    to: list[EmailStr]
    cc: list[EmailStr]

    can_email: bool
    unavailable_reason: str | None = None

    source_row: int