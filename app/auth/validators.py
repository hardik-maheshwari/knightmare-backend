from typing import Any, Optional, Tuple
from quart import Request
from app.logger_setup import get_logger
from app.common.exceptions import ValidationError

logger = get_logger(__name__)

# --- Individual Validation Rules ---


def validate_username(username: Any) -> Optional[str]:
    """
    Validates the username.
    Returns an error message string if invalid, otherwise None.
    """
    if not isinstance(username, str) or not username.strip():
        return "Username must be a non-empty string."
    if len(username) < 3:
        return "Username must be at least 3 characters long."

    return None


def validate_password(password: Any) -> Optional[str]:
    """
    Validates the password.
    Returns an error message string if invalid, otherwise None.
    """
    if not isinstance(password, str) or not password:
        return "Password must be a non-empty string."
    if len(password) < 1:
        return "Password must be at least 8 characters long."

    return None


async def user_input_validator(request: Request) -> Tuple[str, str]:
    """
    Parses and validates user registration input from a request.

    Raises:
        ValidationError: If the input is invalid, malformed, or missing.

    Returns:
        A tuple of (username, password) on successful validation.
    """
    try:
        data = await request.get_json()
        if not data:
            logger.warning("Request attempt with empty or invalid JSON body.")
            raise ValidationError("Request body must be valid JSON.")

    except Exception as e:
        logger.warning(f"Failed to parse JSON from request body: {e}")
        raise ValidationError("Invalid request format. Expected JSON.")

    username = data.get("username")
    password = data.get("password")

    username_error = validate_username(username)
    if username_error:
        logger.warning(f"Invalid input: {username_error}")
        raise ValidationError(username_error)

    password_error = validate_password(password)
    if password_error:
        logger.warning(f"Invalid input: {password_error}")
        raise ValidationError(password_error)

    logger.info(f"User input for '{username}' validated successfully.")
    return username, password
