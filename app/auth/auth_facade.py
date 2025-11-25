import datetime
from typing import Any, Dict
import jwt
from quart_bcrypt import Bcrypt
from app.auth.exceptions import InvalidCredentialsError, UsernameTakenError
from app.auth.models import User
from app.auth.repository import AuthRepository
from app.logger_setup import get_logger

logger = get_logger(__name__)


class AuthFacade:
    def __init__(self, auth_repo: AuthRepository, bcrypt: Bcrypt, secret_key: str):
        self.auth_repo = auth_repo
        self.bcrypt = bcrypt
        self.secret_key = secret_key

    async def register(self, username: str, password: str) -> User:
        """
        Orchestrates the user registration process.

        Raises:
            UsernameTakenError: If the username already exists in the database.
        """
        logger.debug(f"FACADE: Registering user '{username}'.")

        # 1. Check if the username is already taken.
        existing_user = await self.auth_repo.get_user_by_username(username)
        if existing_user:
            logger.warning(
                f"Registration failed: Username '{username}' is already taken."
            )
            raise UsernameTakenError(f"Username '{username}' is already taken.")

        logger.debug(f"Username '{username}' is available.")

        # 2. Hash the password.
        hashed_password_bytes = await self.bcrypt.async_generate_password_hash(password)
        logger.debug("Password hashed successfully.")

        # 3. Create the new User domain object.
        new_user = User(
            username=username,
            password_hash=hashed_password_bytes.decode("utf-8"),
        )

        # 4. Delegate persistence to the repository.
        created_user = await self.auth_repo.save_user(new_user)

        logger.info(
            f"FACADE: User '{username}' registration orchestrated successfully. ID: {created_user.user_id}"
        )
        return created_user

    async def login(self, username: str, password: str) -> str:
        """
        Orchestrates user login and authentication, returning a JWT on success.

        Raises:
            InvalidCredentialsError: If the username is not found or the password is incorrect.
        """
        logger.debug(f"FACADE: Attempting login for user '{username}'.")

        # 1. Find the user via the repository.
        user = await self.auth_repo.get_user_by_username(username)
        if not user:
            logger.warning(f"Login failed: User '{username}' not found.")
            raise InvalidCredentialsError("Invalid username or password.")

        # 2. Check the password using the bcrypt utility.
        is_password_correct = await self.bcrypt.async_check_password_hash(
            user.password_hash, password
        )
        if not is_password_correct:
            logger.warning(f"Login failed: Incorrect password for user '{username}'.")
            raise InvalidCredentialsError("Invalid username or password.")

        # 3. Generate the JWT payload.
        logger.debug(f"Password for '{username}' is correct. Generating JWT.")
        payload: Dict[str, Any] = {
            "user_id": user.user_id,
            "exp": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=24),
            "iat": datetime.datetime.now(datetime.timezone.utc),
        }

        # 4. Encode the token with the injected secret key.
        token = jwt.encode(payload, self.secret_key, algorithm="HS256")

        logger.info(f"FACADE: User '{username}' authenticated successfully.")
        return token
