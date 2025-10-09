from functools import wraps
from typing import Any, Callable, Awaitable

import jwt
from quart import Response, g, jsonify, request, current_app
from sqlalchemy.ext.asyncio import AsyncSession

# --- Import our tools and exceptions ---
from app.auth.exceptions import UserNotFoundError
from app.common.exceptions import ValidationError
from app.common.response_utils import create_error_response
from app.logger_setup import get_logger

# from .models import User
from .repository import AuthRepository

logger = get_logger(__name__)

RouteCallable = Callable[..., Awaitable[tuple[Response, int]]]

def token_required(f: RouteCallable) -> RouteCallable:
    """
    A decorator to ensure a valid JWT is present and provides the user.
    It delegates the actual user fetching (with caching) to the AuthRepository.
    """

    @wraps(f)
    async def decorated_function(*args: Any, **kwargs: Any) -> tuple[Response, int]:
        logger.debug("--- @token_required: Execution started ---")

        try:
            # --- RESPONSIBILITY 1: Token Extraction & Decoding ---
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                raise ValidationError("Authorization header is missing or malformed.")

            token = auth_header.split(" ")[1]
            logger.debug("Token successfully extracted from header.")

            payload = jwt.decode(
                token, current_app.config["SECRET_KEY"], algorithms=["HS256"]  # type: ignore
            )
            user_id = payload.get("user_id")
            if not user_id:
                raise jwt.InvalidTokenError("Token payload is missing 'user_id'.")

            logger.debug(f"JWT decoded for user_id: {user_id}")

            # --- RESPONSIBILITY 2: User Fetching (Delegated) ---
            session: AsyncSession = g.session
            repo = AuthRepository(session)

            # Here's the magic! One clean call.
            current_user = await repo.get_user_by_id_with_cache(user_id)

            if not current_user:
                # The token was valid, but the user ID it points to no longer exists.
                raise UserNotFoundError()

        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, ValidationError) as e:
            error_message = (
                "Token has expired."
                if isinstance(e, jwt.ExpiredSignatureError)
                else "Invalid or malformed token."
            )
            logger.warning(f"Authentication failed: {error_message} - {e}")
            response, status = create_error_response(error_message, 401)
            return jsonify(response), status

        except UserNotFoundError:
            logger.warning(f"Token valid, but user not found in DB.")
            response, status = create_error_response("User not found.", 401)
            return jsonify(response), status

        except Exception as e:
            logger.error(f"Unexpected error in token_required: {e}", exc_info=True)
            response, status = create_error_response("Internal Server Error", 500)
            return jsonify(response), status

        # --- If all is well, inject the user and proceed ---
        logger.debug(f"User '{current_user.username}' authenticated successfully.")
        kwargs["current_user"] = current_user

        logger.debug("--- @token_required: Passing control to the route function. ---")
        return await f(*args, **kwargs)

    return decorated_function
