import json
from datetime import datetime

from typing import Any, Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User
from app.logger_setup import get_logger
from app.extensions import redis_client

logger = get_logger(__name__)


class AuthRepository:
    """
    This class handles all database operations related to authentication.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        logger.debug("AuthRepository initialized with a new session.")

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """
        Retrieves a user from the database by their username.
        """
        logger.debug(f"Querying for user with username: '{username}'")
        statement = select(User).where(User.username == username)

        result = await self.session.execute(statement)
        user = result.scalars().first()

        if user:
            logger.debug(f"Found user: {user}")
        else:
            logger.debug(f"User with username '{username}' not found.")

        return user

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """
        Retrieves a user from the database by their primary key ID.
        """
        logger.debug(f"Querying for user with user_id: {user_id}")
        statement = select(User).where(User.user_id == user_id)

        result = await self.session.execute(statement)
        user = result.scalars().first()

        if user:
            logger.debug(f"Found user: {user}")
        else:
            logger.debug(f"User with user_id {user_id} not found.")

        return user

    async def save_user(self, user: User) -> User:
        """
        Adds a new user to the database.
        """
        logger.debug(f"Adding new user '{user.username}' to the session.")
        self.session.add(user)

        logger.debug("Flushing session to send INSERT to the database.")
        await self.session.flush()

        # logger.debug(
        #     f"Refreshing user instance to get new DB-generated values (ID, timestamps)."
        # )
        # await self.session.refresh(user)

        # logger.debug(f"User instance after refresh: {user}")
        return user

    async def get_user_by_id_with_cache(self, user_id: int) -> Optional[User]:
        """
        Retrieves a user by ID, using a read-through cache pattern.
        1. Try to fetch from Redis.
        2. If miss, fetch from PostgreSQL.
        3. If found in DB, "warm" the cache by saving the result to Redis.
        """
        cache_key = f"user:{user_id}"
        logger.debug(
            f"CACHE-FETCH: Attempting to get user from cache with key: {cache_key}"
        )

        # 1. --- Try to fetch from Redis ---
        cached_user_str = await redis_client.get(cache_key)
        if cached_user_str:
            logger.debug(f"CACHE-FETCH: Cache hit for user {user_id}.")
            user_data = json.loads(cached_user_str)
            user = User()

            # 2. Manually set the attributes you have from the cache.
            user.user_id = user_data["user_id"]
            user.username = user_data["username"]
            user.created_at = datetime.fromisoformat(user_data["created_at"])
            user.updated_at = datetime.fromisoformat(user_data["updated_at"])

            # 3. Return the partially-hydrated, secure object.
            #    The 'user.password_hash' attribute will be None, which is correct and safe
            #    because this object will never be used for password verification.
            return user

        logger.debug(f"CACHE-FETCH: Cache miss for user {user_id}. Fetching from DB.")

        user = await self.get_user_by_id(user_id)

        if not user:
            # User not found in DB either, so we're done.
            return None

        logger.debug(f"CACHE-FETCH: DB hit for user {user_id}. Warming the cache.")
        user_data_to_cache: Dict[str, Any] = {
            "user_id": user.user_id,
            "username": user.username,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
        }
        # Set with an expiration of 5 minutes (300 seconds)
        await redis_client.setex(cache_key, 300, json.dumps(user_data_to_cache))

        return user
