import secrets
from redis.asyncio.client import Redis as AsyncRedis
from app.auth.exceptions import InvalidCredentialsError, UserNotFoundError
from app.auth.models import User
from app.auth.repository import AuthRepository
from app.game.exceptions import GameNotFoundError, UserNotPlayerError
from app.game.repository import GameRepository
from app.logger_setup import get_logger

logger = get_logger(__name__)


class WebSocketAuthFacade:
    def __init__(
        self, auth_repo: AuthRepository, game_repo: GameRepository, redis_client: AsyncRedis
    ):
        self.auth_repo = auth_repo
        self.game_repo = game_repo
        self.redis_client = redis_client

    async def issue_ticket(self, game_id: str, current_user: User) -> str:
        """Authorizes a user for a game and issues a single-use WebSocket ticket.

        This method serves as the authorization gateway for establishing a WebSocket
        connection. It verifies that the user is a legitimate player in the
        specified game before generating a cryptographically secure, short-lived
        ticket. This ticket is then stored in Redis to be consumed once by the
        WebSocket connection handler.

        Args:
            game_id: The ID of the game the user wants to connect to.
            current_user: The authenticated user object requesting the ticket.

        Returns:
            The generated, URL-safe ticket string to be used for authentication.

        Raises:
            GameNotFoundError: If no game with the given `game_id` is found.
            UserNotPlayerError: If the `current_user` is not a participant in the game.
        """
        game = await self.game_repo.get_game_by_id(game_id)

        if not game:
            raise GameNotFoundError(f"Game not found for id {game_id}")

        is_player = (
            current_user.user_id == game.white_player_id
            or current_user.user_id == game.black_player_id
        )

        if not is_player:
            logger.warning(
                f"FORBIDDEN: User '{current_user.username}' attempted to access game '{game_id}' without permission."
            )

            raise UserNotPlayerError(f"{current_user.username} is not part of the game")

        ticket = secrets.token_urlsafe(24)

        await self.redis_client.setex(f"ws_ticket:{ticket}", 15, current_user.user_id)

        logger.info(
            f"Issued WebSocket ticket for user '{current_user.username}' for game '{game_id}'."
        )

        return ticket

    async def validate_ticket(self, ticket: str) -> User:
        """
        Validates a single-use WebSocket ticket, consumes it, and returns
        the authenticated user.

        Raises:
            InvalidCredentialsError: If the ticket is missing, invalid, or expired.
            UserNotFoundError: If the user ID from a valid ticket does not exist.
        """
        if not ticket:
            logger.warning("WS auth failed: No ticket provided.")
            raise InvalidCredentialsError("Authentication ticket is missing.")

        redis_key = f"ws_ticket:{ticket}"

        user_id_bytes = await self.redis_client.get(redis_key)

        if user_id_bytes is None:
            logger.warning(f"WS auth failed: Invalid or expired ticket used.")
            raise InvalidCredentialsError(
                "Authentication ticket is invalid or has expired."
            )

        # 2. Consume the single-use ticket immediately.
        await self.redis_client.delete(redis_key)
        logger.debug(f"Consumed single-use WS ticket from key: {redis_key}")

        try:
            user_id = int(user_id_bytes)
        except (ValueError, TypeError):
            logger.error(
                f"Invalid user ID '{user_id_bytes}' found in Redis for ticket."
            )
            raise InvalidCredentialsError("Corrupted authentication ticket.")

        user = await self.auth_repo.get_user_by_id_with_cache(user_id)

        if not user:
            # This is a rare edge case where the user was deleted between
            # the ticket being issued and being used.
            logger.warning(
                f"WS auth failed: User with ID {user_id} from valid ticket not found."
            )
            raise UserNotFoundError(
                "User associated with this ticket no longer exists."
            )

        logger.info(
            f"WS ticket validated successfully for user '{user.username}' (ID: {user.user_id})."
        )
        return user
