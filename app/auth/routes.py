import datetime
from typing import Dict, Any
import jwt
from quart import Blueprint, g, jsonify, request, current_app
from quart_bcrypt import Bcrypt
from app.auth.exceptions import InvalidCredentialsError, UsernameTakenError
from app.logger_setup import get_logger  # type: ignore
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

        hashed_password = await bcrypt.async_generate_password_hash(password)  # type: ignore
        logger.debug("Password hashed successfully.")

        # 2. Database Interaction
        session: AsyncSession = g.session
        repo = AuthRepository(session)

        logger.debug(f"Checking for existing user '{username}'...")
        existing_user = await repo.get_user_by_username(username)  # type: ignore

        if existing_user:
            raise UsernameTakenError(f"Username '{username}' is already taken.")

        logger.debug(f"Username '{username}' is available. Creating new user object.")
        new_user = User(
            username=username,
            password_hash=hashed_password.decode("utf-8"),
        )

        created_user = await repo.create_user(new_user)

        logger.info(
            f"User '{username}' created successfully with ID: {created_user.user_id}."
        )

        response_dict, status_code = create_success_response(
            data={"message": f"User '{username}' created successfully."},
            status_code=201,
        )
        return jsonify(response_dict), status_code

    except ValidationError as e:
        logger.warning(f"Input validation failed: {e.message}")
        response, status = create_error_response(e.message, e.status_code)
        return jsonify(response), status

    except UsernameTakenError as e:
        logger.warning(f"Registration failed for '{username}': {e}")
        response_dict, status_code = create_error_response(str(e), 409)
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
        repo = AuthRepository(session)

        # 2. Find the user
        logger.debug(f"Attempting to find user '{username}'...")
        existing_user = await repo.get_user_by_username(username)  # type: ignore

        if not existing_user:
            raise InvalidCredentialsError()

        # 3. Check password
        logger.debug(
            f"User found. Checking password for user ID: {existing_user.user_id}"
        )
        is_password_correct = await bcrypt.async_check_password_hash(
            existing_user.password_hash, password  # type: ignore
        )

        if not is_password_correct:
            raise InvalidCredentialsError()

        # 4. Generate JWT
        logger.debug("Password is correct. Generating JWT.")
        payload: Dict[str, Any] = {
            "user_id": existing_user.user_id,
            "exp": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=24),
            "iat": datetime.datetime.now(datetime.timezone.utc),
        }
        token = jwt.encode(
            payload, current_app.config["SECRET_KEY"], algorithm="HS256"  # type: ignore
        )
        logger.info(f"User '{username}' logged in successfully.")

        response_dict, status_code = create_success_response(data={"token": token})
        return jsonify(response_dict), status_code

    except ValidationError as e:

        logger.warning(f"Login validation failed: {e.message}")
        response, status = create_error_response(e.message, e.status_code)
        return jsonify(response), status

    except InvalidCredentialsError:
        err_msg = "Invalid username or password."
        logger.warning(f"Login failed for user '{username}': {err_msg}")
        response, status = create_error_response(err_msg, 401)
        return jsonify(response), status

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
