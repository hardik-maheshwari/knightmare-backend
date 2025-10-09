from app.logger_setup import get_logger
from typing import Tuple, TypedDict, Any

logger = get_logger(__name__)


class ApiSuccessResponse(TypedDict):
    status: int
    data: Any


class ApiErrorResponse(TypedDict):
    status: int
    error: str


def create_success_response(
    data: Any, status_code: int = 200, **kwargs: Any
) -> Tuple[ApiSuccessResponse, int]:
    """Creates a standardized success response dictionary and status code."""
    response_dictionary: ApiSuccessResponse = {
        "status": status_code,
        "data": data,
        **kwargs,
    }  # type: ignore
    return response_dictionary, status_code


def create_error_response(
    error_message: str, status_code: int = 400, **kwargs: Any
) -> Tuple[ApiErrorResponse, int]:
    """Creates a standardized error response dictionary and status code."""
    response_dictionary: ApiErrorResponse = {
        "status": status_code,
        "error": error_message,
        **kwargs,
    }  # type: ignore
    return response_dictionary, status_code
