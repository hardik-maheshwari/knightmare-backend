from pydantic import BaseModel, Field, field_validator


class UserAuthRequest(BaseModel):
    """
    Schema for Registration and Login.
    Enforces username alphanumeric rules and password length.
    """

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="User's unique handle. Must be alphanumeric.",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,  # Good practice to prevent DoS via massive passwords
        description="Plaintext password.",
    )

    @field_validator("username")
    @classmethod
    def username_must_be_alphanumeric(cls, v: str) -> str:
        # Custom logic that standard types can't cover
        if not v.isalnum():
            raise ValueError("Username must be alphanumeric.")
        return v


class MoveRequest(BaseModel):
    """
    Schema for making a Chess Move.
    Validates the UCI format (e.g., 'e2e4', 'a7a8q').
    """

    move: str = Field(
        ...,
        min_length=4,
        max_length=5,
        pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$",
        description="UCI format move string (source+target+promotion)",
    )
