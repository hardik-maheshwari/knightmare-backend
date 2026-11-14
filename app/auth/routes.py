import datetime
from quart import Blueprint, g, jsonify, request, current_app
from quart_bcrypt import Bcrypt
from app.auth.auth_facade import AuthFacade
from app.common.schemas import UserAuthRequest
from app.logger_setup import get_logger
from app.common.response_utils import create_success_response
from quart_rate_limiter import rate_limit
from .models import User
from .repository import AuthRepository
from .decorators import token_required
from sqlalchemy.ext.asyncio import AsyncSession

# Errors are not caught here: they propagate to the handlers in app/errors.py
# (UsernameTakenError -> 409, InvalidCredentialsError -> 401, validation -> 400,
# anything else -> 500), and the session is rolled back for any error response.

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
logger = get_logger(__name__)
bcrypt = Bcrypt()


def _build_auth_facade() -> AuthFacade:
    session: AsyncSession = g.session
    secret_key = current_app.config["SECRET_KEY"]  # type: ignore
    return AuthFacade(AuthRepository(session), bcrypt, secret_key)  # type: ignore


@auth_bp.route("/test", methods=["GET"])
async def test():
    logger.info("Received hit")
    return jsonify("hello"), 200


@auth_bp.route("/register/", methods=["POST"])
async def register_user():
    """
    Handles new user registration.
    """
    logger.debug("--- /register: Request received ---")

    body = await request.get_json(silent=True)
    validated_data = UserAuthRequest.model_validate(body)
    username = validated_data.username

    created_user = await _build_auth_facade().register(
        username, validated_data.password
    )

    logger.info(
        f"User '{username}' created successfully with ID: {created_user.user_id}."
    )
    response_dict, status_code = create_success_response(
        data={"message": f"User '{created_user.username}' created successfully."},
        status_code=201,
    )
    return jsonify(response_dict), status_code


@auth_bp.route("/login/", methods=["POST"])
@rate_limit(5, datetime.timedelta(minutes=1))  # <-- 5 requests per 1 minute
async def login():
    """
    Handles user login.
    """
    logger.debug("--- /login: Request received ---")

    body = await request.get_json(silent=True)
    validated_data = UserAuthRequest.model_validate(body)
    username = validated_data.username

    token = await _build_auth_facade().login(username, validated_data.password)

    logger.info(f"User '{username}' logged in successfully.")
    response_dict, status_code = create_success_response(data={"token": token})
    return jsonify(response_dict), status_code


@auth_bp.route("/profile/", methods=["GET"])
@token_required
async def get_user_profile(current_user: User):
    """
    A protected route to get the current user's profile.
    """
    logger.debug(
        f"--- /profile: Request received. Authenticated user: {current_user.username} ---"
    )

    response_dict, status_code = create_success_response(
        data={
            "user_id": current_user.user_id,
            "username": current_user.username,
            "member_since": current_user.created_at.isoformat(),
        }
    )

    logger.info(f"Successfully served profile for user '{current_user.username}'.")
    return jsonify(response_dict), status_code
