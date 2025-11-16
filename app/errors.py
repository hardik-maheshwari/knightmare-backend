from quart import Quart, Response, jsonify, request
from .common.response_utils import create_error_response
from .logger_setup import get_logger
from .game.exceptions import GameNotFoundError, UserNotPlayerError, MoveNotPossibleError
from .auth.exceptions import UsernameTakenError, InvalidCredentialsError
from .common.exceptions import ValidationError
from quart_rate_limiter import RateLimitExceeded

logger = get_logger(__name__)


def register_error_handlers(app: Quart):
    @app.errorhandler(RateLimitExceeded)
    async def handle_rate_limit_exceeded(e: RateLimitExceeded) -> tuple[Response, int]:
        """
        Custom handler for when a rate limit is exceeded.
        This function is registered with Quart and will be called automatically.
        """
        logger.warning(
            f"Rate limit exceeded for request: {request.method} {request.path}. "
            f"Client will need to wait {e.retry_after} seconds."
        )

        response_dict, status_code = create_error_response(
            f"Rate limit exceeded. Try again in {e.retry_after} seconds.", 429
        )

        logger.debug(f"Returning 429 Too Many Requests error response.")
        return jsonify(response_dict), status_code

    @app.errorhandler(GameNotFoundError)
    async def handle_game_not_found(e: GameNotFoundError):
        logger.warning(f"Caught GameNotFoundError: {e}")
        response, status = create_error_response(str(e), 404)
        return jsonify(response), status

    # Example for 403
    @app.errorhandler(UserNotPlayerError)
    async def handle_user_not_player(e: UserNotPlayerError):
        logger.warning(f"Caught UserNotPlayerError: {e}")
        response, status = create_error_response(str(e), 403)
        return jsonify(response), status

    @app.errorhandler(MoveNotPossibleError)
    async def handle_move_not_possible(e: MoveNotPossibleError):
        logger.warning(f"Caught illegal move attempt: {e}")
        response, status = create_error_response(str(e), 409)  # 409 Conflict
        return jsonify(response), status

    # Example for 409
    @app.errorhandler(UsernameTakenError)
    # You can stack handlers for exceptions that return the same status code
    async def handle_conflict(e: Exception):
        logger.warning(f"Caught Conflict Error ({type(e).__name__}): {e}")
        response, status = create_error_response(str(e), 409)
        return jsonify(response), status

    # Example for 401
    @app.errorhandler(InvalidCredentialsError)
    async def handle_invalid_credentials(e: InvalidCredentialsError):
        logger.warning(f"Caught InvalidCredentialsError: Invalid username or password.")
        response, status = create_error_response("Invalid username or password.", 401)
        return jsonify(response), status

    # Example for 400
    @app.errorhandler(ValidationError)
    async def handle_validation_error(e: ValidationError):
        logger.warning(f"Caught ValidationError: {e.message}")
        response, status = create_error_response(e.message, e.status_code)
        return jsonify(response), status
