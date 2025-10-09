class AuthError(Exception):
    """Base exception for all authentication-related errors."""

    pass


class UsernameTakenError(AuthError):
    """Raised during registration if the username already exists."""

    pass


class InvalidCredentialsError(AuthError):
    """Raised during login if the username/password combination is incorrect."""

    pass


class UserNotFoundError(AuthError):
    """Raised when a user ID from a valid token is not found in the database."""

    pass
