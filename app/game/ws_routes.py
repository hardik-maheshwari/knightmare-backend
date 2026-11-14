import asyncio
import json
from typing import Any, Dict, cast
from quart import Blueprint, current_app, websocket
from quart.wrappers import Websocket
from app.auth.exceptions import InvalidCredentialsError, UserNotFoundError
from app.auth.models import User
from app.dependency_injection import get_container
from app.extensions import AsyncSessionLocal
from app.game.exceptions import GameNotFoundError
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
    is_registered = False
    ws_manager = cast(GameWebSocketManager, current_app.ws_manager)  # type: ignore

    logger.info(f"--- WebSocket connection attempt for game '{game_id}' ---")

    try:
        # The DB session is scoped to auth + initial sync ONLY. Holding it for the
        # whole connection would pin one pooled DB connection per open socket
        # (idle in transaction) and exhaust the pool after a handful of games.
        async with AsyncSessionLocal() as session:
            container = get_container(session)
            ws_auth_service = container.get_ws_auth_facade()
            game_facade = container.get_game_facade()

            # 1. Authenticate (the ticket must have been issued for THIS game)
            ticket = ws.args.get("ticket")
            if not ticket:
                raise InvalidCredentialsError("Authentication ticket is missing.")
            current_user = await ws_auth_service.validate_ticket(ticket, game_id)
            logger.info(
                f"WS connection for user '{current_user.username}' authenticated."
            )

            # 2. Register for broadcasts BEFORE reading state, so no update that
            #    lands between the read and the registration is missed.
            await ws_manager.connect_to_game(game_id, ws)
            is_registered = True

            # 3. Read the initial state for THIS client
            initial_state_payload: Dict[str, Any] = (
                await game_facade.get_serialized_game_state(game_id)
            )
        # Session closed here; its connection is back in the pool.

        logger.debug(
            f"Sending initial game state for '{game_id}' to '{current_user.username}'."
        )
        await ws.send(json.dumps(initial_state_payload))

        # 4. Keep the connection alive until the client disconnects.
        while True:
            await ws.receive()

    except (InvalidCredentialsError, UserNotFoundError) as e:
        logger.warning(f"WS auth failed for game '{game_id}': {e}")
        await ws.close(1008, "Invalid or expired ticket")
    except GameNotFoundError as e:
        logger.warning(f"WS connection rejected: Game '{game_id}' not found. {e}")
        await ws.close(1011, "Game not found")
    except asyncio.CancelledError:
        # Clean disconnect, not an error. Re-raise so Quart finishes the task.
        if current_user:
            logger.info(
                f"WS connection for '{current_user.username}' in game '{game_id}' closed."
            )
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error in websocket for game '{game_id}': {e}",
            exc_info=True,
        )
        await ws.close(1011, "Internal server error")
    finally:
        if is_registered:
            await ws_manager.disconnect_from_game(game_id, ws)
        logger.debug(f"WS cleanup complete for game '{game_id}'.")
