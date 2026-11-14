from quart import Quart, Response, g, jsonify, request
from pydantic import ValidationError as PydanticValidationError
from quart_rate_limiter import RateLimitExceeded
from werkzeug.exceptions import HTTPException

from .common.response_utils import create_error_response
from .logger_setup import get_logger
from .game.exceptions import (
    AlreadyInGameError,
    GameError,
    GameNotFoundError,
    GameNotJoinableError,
    MoveNotPossibleError,
    TimeoutLossError,
    UserNotPlayerError,
)
from .auth.exceptions import (
    InvalidCredentialsError,
    UserNotFoundError,
    UsernameTakenError,
)
from .common.exceptions import ValidationError

logger = get_logger(__name__)

ErrorResult = tuple[Response, int]


def _error(message: str, status: int) -> ErrorResult:
    response, status_code = create_error_response(message, status)
    return jsonify(response), status_code


def register_error_handlers(app: Quart):
    """
    Central exception -> HTTP mapping. Routes just raise; they don't catch.

    Quart picks the handler for the most specific class in the exception's MRO,
    so e.g. TimeoutLossError uses its own handler, not MoveNotPossibleError's.
    """

    @app.errorhandler(RateLimitExceeded)
    async def handle_rate_limit_exceeded(e: RateLimitExceeded) -> ErrorResult:
        logger.warning(
            f"Rate limit exceeded for request: {request.method} {request.path}. "
            f"Client will need to wait {e.retry_after} seconds."
        )
        return _error(f"Rate limit exceeded. Try again in {e.retry_after} seconds.", 429)

    # --- 400: bad input ---
    @app.errorhandler(ValidationError)
    async def handle_validation_error(e: ValidationError) -> ErrorResult:
        logger.warning(f"Caught ValidationError: {e.message}")
        return _error(e.message, e.status_code)

    @app.errorhandler(PydanticValidationError)
    async def handle_pydantic_error(e: PydanticValidationError) -> ErrorResult:
        first = e.errors()[0]
        field = ".".join(str(part) for part in first.get("loc", ())) or "request body"
        logger.warning(f"Request validation failed: {e.errors()}")
        return _error(f"Invalid {field}: {first.get('msg', 'invalid value')}", 400)

    # --- 401: authentication ---
    @app.errorhandler(InvalidCredentialsError)
    async def handle_invalid_credentials(e: InvalidCredentialsError) -> ErrorResult:
        logger.warning("Caught InvalidCredentialsError.")
        return _error("Invalid username or password.", 401)

    @app.errorhandler(UserNotFoundError)
    async def handle_user_not_found(e: UserNotFoundError) -> ErrorResult:
        logger.warning(f"Caught UserNotFoundError: {e}")
        return _error("User not found.", 401)

    # --- 403 / 404 ---
    @app.errorhandler(UserNotPlayerError)
    async def handle_user_not_player(e: UserNotPlayerError) -> ErrorResult:
        logger.warning(f"Caught UserNotPlayerError: {e}")
        return _error(str(e), 403)

    @app.errorhandler(GameNotFoundError)
    async def handle_game_not_found(e: GameNotFoundError) -> ErrorResult:
        logger.warning(f"Caught GameNotFoundError: {e}")
        return _error(str(e), 404)

    # --- 409: conflicts with current state ---
    @app.errorhandler(UsernameTakenError)
    @app.errorhandler(GameNotJoinableError)
    @app.errorhandler(AlreadyInGameError)
    @app.errorhandler(MoveNotPossibleError)
    async def handle_conflict(e: Exception) -> ErrorResult:
        logger.warning(f"Caught conflict ({type(e).__name__}): {e}")
        return _error(str(e), 409)

    @app.errorhandler(TimeoutLossError)
    async def handle_timeout_loss(e: TimeoutLossError) -> ErrorResult:
        # The move is rejected but the game-over state must persist.
        g.force_commit = True
        logger.info(f"Move rejected due to flag fall: {e}")
        return _error(str(e), 409)

    # --- Other domain rule violations (e.g. resigning a finished game) ---
    @app.errorhandler(GameError)
    async def handle_game_error(e: GameError) -> ErrorResult:
        logger.warning(f"Caught GameError ({type(e).__name__}): {e}")
        return _error(str(e), 400)

    # --- Framework HTTP errors (404 route, 405, malformed JSON...) ---
    @app.errorhandler(HTTPException)
    async def handle_http_exception(e: HTTPException) -> ErrorResult:
        return _error(e.description or e.name, e.code or 500)

    # --- Last resort: never leak internals ---
    @app.errorhandler(Exception)
    async def handle_unexpected(e: Exception) -> ErrorResult:
        logger.error(
            f"Unhandled error on {request.method} {request.path}: {e}", exc_info=True
        )
        return _error("Internal Server Error", 500)
