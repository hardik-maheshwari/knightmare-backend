import asyncio
import json
from typing import cast
from quart import Blueprint, current_app, websocket
from quart.wrappers import Websocket
from app.auth.exceptions import InvalidCredentialsError, UserNotFoundError
from app.auth.models import User
from app.auth.repository import AuthRepository
from app.auth.websocket_auth_facade import WebSocketAuthFacade
from app.dependency_injection import get_container
from app.extensions import AsyncSessionLocal, redis_client
from app.game.exceptions import GameNotFoundError
from app.game.facade import GameFacade
from app.game.repository import GameRepository
from app.managers.game_manager import GameWebSocketManager
from app.logger_setup import get_logger


logger = get_logger(__name__)

ws_bp = Blueprint("game_ws", __name__)


@ws_bp.websocket("/api/games/<string:game_id>/ws")
async def game_websocket(game_id: str):
    """
    Handles the websocket connection lifecycle, delegating all business logic
    to the appropriate facades and services.
    """
    ws = websocket._get_current_object()  # type: ignore
    assert isinstance(ws, Websocket)
    current_user: User | None = None
    ws_manager = cast(GameWebSocketManager, current_app.ws_manager)  # type: ignore

    logger.info(f"--- WebSocket connection attempt for game '{game_id}' ---")

    async with AsyncSessionLocal() as session:
        try:
            # 1. Instantiate Dependencies
            container = get_container(session)
            ws_auth_service = container.get_ws_auth_facade()
            game_facade = container.get_game_facade()

            # 2. Authenticate the connection using the dedicated service
            ticket = ws.args.get("ticket")

            if not ticket:
                raise InvalidCredentialsError("Authentication ticket is missing.")
            current_user = await ws_auth_service.validate_ticket(ticket)
            logger.info(
                f"WS connection for user '{current_user.username}' authenticated."
            )

            # 3. Register the connection with the manager for future broadcasts
            await ws_manager.connect_to_game(game_id, ws)

            # 4. Perform the initial state sync for THIS client
            logger.debug(
                f"Sending initial game state for '{game_id}' to '{current_user.username}'."
            )
            initial_state_payload = await game_facade.get_serialized_game_state(game_id)
            await ws.send(json.dumps(initial_state_payload))

            # 5. Enter the perpetual listening loop
            # The handler's main job is now just to keep the connection alive.
            while True:
                # We wait here until the client sends a message or disconnects.
                await ws.receive()

        # 6. Handle specific lifecycle exceptions
        except (InvalidCredentialsError, UserNotFoundError) as e:
            logger.warning(f"WS auth failed for game '{game_id}': {e}")
            await ws.close(1008, "Invalid or expired ticket")
        except GameNotFoundError as e:
            logger.warning(f"WS connection rejected: Game '{game_id}' not found. {e}")
            await ws.close(1011, "Game not found")
        except asyncio.CancelledError:
            # This is a clean disconnect, not an error.
            if current_user:
                logger.info(
                    f"WS connection for '{current_user.username}' in game '{game_id}' cancelled cleanly."
                )
        except Exception as e:
            logger.error(
                f"Unexpected error in websocket for game '{game_id}': {e}",
                exc_info=True,
            )
            await ws.close(1011, "Internal server error")
        finally:
            # 7. Guarantee cleanup on any exit path
            if current_user:
                logger.info(
                    f"Disconnecting user '{current_user.username}' from game '{game_id}'."
                )
            await ws_manager.disconnect_from_game(game_id, ws)
            logger.debug(f"WS cleanup complete for game '{game_id}'.")
