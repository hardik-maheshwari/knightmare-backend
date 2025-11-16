import datetime
from quart import Blueprint, g, jsonify, request, current_app
from quart_bcrypt import Bcrypt
from app.auth.auth_facade import AuthFacade
from app.logger_setup import get_logger
from app.common.response_utils import create_error_response, create_success_response
from .validators import *
from quart_rate_limiter import rate_limit
from .models import User
from .repository import AuthRepository
from .decorators import token_required
from sqlalchemy.ext.asyncio import AsyncSession

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
logger = get_logger(__name__)
bcrypt = Bcrypt()


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
    username = None

    try:
        # 1. Validation
        username, password = await user_input_validator(request)
        logger.debug(f"Input for username '{username}' passed validation.")

        session: AsyncSession = g.session
        auth_repo = AuthRepository(session)
        secret_key = current_app.config["SECRET_KEY"]  # type: ignore
        auth_facade = AuthFacade(auth_repo, bcrypt, secret_key)  # type: ignore

        # 3. Delegate the entire business process to the facade.
        created_user = await auth_facade.register(username, password)

        logger.info(
            f"User '{username}' created successfully with ID: {created_user.user_id}."
        )

        response_dict, status_code = create_success_response(
            data={"message": f"User '{created_user.username}' created successfully."},
            status_code=201,
        )
        return jsonify(response_dict), status_code

    except Exception as e:
        log_username = f"for '{username}'" if username else ""
        logger.error(
            f"An unexpected error occurred during user registration {log_username}: {e}",
            exc_info=True,
        )
        response_dict, status_code = create_error_response("Internal Server Error", 500)
        return jsonify(response_dict), status_code


@auth_bp.route("/login/", methods=["POST"])
@rate_limit(5, datetime.timedelta(minutes=1))  # <-- 5 requests per 1 minute
async def login():
    """
    Handles user login.
    """
    logger.debug("--- /login: Request received ---")

    username = None

    try:

        # 1. Validation
        username, password = await user_input_validator(request)
        logger.debug(f"Input for username '{username}' passed validation.")
        session: AsyncSession = g.session
        auth_repo = AuthRepository(session)
        secret_key = current_app.config["SECRET_KEY"]  # type: ignore
        auth_facade = AuthFacade(auth_repo, bcrypt, secret_key)  # type: ignore

        token = await auth_facade.login(username, password)

        logger.info(f"User '{username}' logged in successfully.")

        response_dict, status_code = create_success_response(data={"token": token})
        return jsonify(response_dict), status_code

    except Exception as e:
        log_username = f"for '{username}'" if username else ""
        logger.error(
            f"An unexpected error occurred during login {log_username}: {e}",
            exc_info=True,
        )
        response, status = create_error_response("Internal Server Error", 500)
        return jsonify(response), status


@auth_bp.route("/profile/", methods=["GET"])
@token_required
async def get_user_profile(current_user: User):
    """
    A protected route to get the current user's profile.
    """
    logger.debug(
        f"--- /profile: Request received. Authenticated user: {current_user.username} ---"
    )

    # The decorator has already done all the work. We just use the result.
    response_dict, status_code = create_success_response(
        data={
            "user_id": current_user.user_id,
            "username": current_user.username,
            "member_since": current_user.created_at.isoformat(),
        }
    )

    logger.info(f"Successfully served profile for user '{current_user.username}'.")
    return jsonify(response_dict), status_code
