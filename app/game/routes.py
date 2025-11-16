import asyncio
import json
from typing import Any, Dict, cast
from quart import Blueprint, current_app, jsonify, g, request, websocket
from app.auth.exceptions import InvalidCredentialsError, UserNotFoundError
from app.auth.models import User
from app.auth.decorators import token_required
from app.auth.repository import AuthRepository
from app.auth.websocket_auth_facade import WebSocketAuthFacade
from app.common.exceptions import ValidationError
from app.common.response_utils import create_success_response, create_error_response
from app.extensions import AsyncSessionLocal, redis_client
from quart.wrappers import Websocket

# from app.game.models import Game
from app.game.exceptions import GameNotFoundError
from app.game.facade import GameFacade
from app.logger_setup import get_logger
from .repository import GameRepository
from sqlalchemy.ext.asyncio import AsyncSession
from app.websocket_manager import WebSocketManager


game_bp = Blueprint("game", __name__, url_prefix="/api/games")

logger = get_logger(__name__)


@game_bp.route("/<string:game_id>/ws-ticket/", methods=["POST"])
@token_required
async def get_websocket_ticket(game_id: str, current_user: User):
    """
    Generates a short-lived, single-use ticket for authenticating a WebSocket connection.
    """
    try:
        session: AsyncSession = g.session
        game_repo = GameRepository(session)
        auth_repo = AuthRepository(session)

        ws_auth_service = WebSocketAuthFacade(auth_repo, game_repo, redis_client)

        ticket = await ws_auth_service.issue_ticket(game_id, current_user)

        response, status = create_success_response(data={"ticket": ticket})
        return jsonify(response), status

    except Exception as e:
        logger.error(
            f"Unexpected error issuing WS ticket for user '{current_user.username}': {e}",
            exc_info=True,
        )
        response, status = create_error_response("Internal Server Error", 500)
        return jsonify(response), status


@game_bp.websocket("/<string:game_id>/ws")
async def game_websocket(game_id: str):
    """
    Handles the websocket connection lifecycle, delegating all business logic
    to the appropriate facades and services.
    """
    ws = websocket._get_current_object()  # type: ignore
    assert isinstance(ws, Websocket)
    current_user: User | None = None
    ws_manager = cast(WebSocketManager, current_app.ws_manager)

    logger.info(f"--- WebSocket connection attempt for game '{game_id}' ---")

    async with AsyncSessionLocal() as session:
        try:
            # 1. Instantiate Dependencies
            auth_repo = AuthRepository(session)
            game_repo = GameRepository(session)

            # The services that contain our business logic
            ws_auth_service = WebSocketAuthFacade(auth_repo, game_repo, redis_client)
            game_facade = GameFacade(game_repo, auth_repo, ws_manager)

            # 2. Authenticate the connection using the dedicated service
            ticket = ws.args.get("ticket")

            if not ticket:
                raise InvalidCredentialsError("Authentication ticket is missing.")
            current_user = await ws_auth_service.validate_ticket(ticket)
            logger.info(
                f"WS connection for user '{current_user.username}' authenticated."
            )

            # 3. Register the connection with the manager for future broadcasts
            await ws_manager.connect(game_id, ws)

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
            await ws_manager.disconnect(game_id, ws)
            logger.debug(f"WS cleanup complete for game '{game_id}'.")


@game_bp.route("/", methods=["POST"])
@token_required
async def create_game(current_user: User):
    """
    Creates a new game and assigns the creator as the first player.
    """
    logger.debug(
        f"--- create_game: Request received from user '{current_user.username}' ---"
    )
    try:

        session: AsyncSession = g.session
        game_repo = GameRepository(session)
        auth_repo = AuthRepository(session)  # Still needed by the facade
        ws_manager = cast(WebSocketManager, current_app.ws_manager)  # type: ignore

        facade = GameFacade(game_repo, auth_repo, ws_manager)

        new_game = await facade.create_game(creator=current_user)

        game_data: Dict[str, Any] = {
            "game_id": new_game.game_id,
            "white_player_id": new_game.white_player_id,
            "black_player_id": new_game.black_player_id,
            "status": new_game.status.value,
            "created_at": new_game.created_at.isoformat(),
            "updated_at": new_game.updated_at.isoformat(),
        }

        response_data, status_code = create_success_response(
            data=game_data, status_code=201
        )

        logger.info(
            f"Game {new_game.game_id} created successfully for user {current_user.username}."
        )
        return jsonify(response_data), status_code

    except Exception as e:
        logger.error(
            f"Error creating game for user {current_user.user_id}: {e}", exc_info=True
        )
        response_dict, status_code = create_error_response("Internal Server Error", 500)
        return jsonify(response_dict), status_code


@game_bp.route("/<string:game_id>/join/", methods=["POST"])
@token_required
async def join_game_route(game_id: str, current_user: User):
    """
    Allows the current user to join an existing game that is waiting for an opponent.
    """
    logger.debug(
        f"--- join_game: Request received from user '{current_user.username}' for game '{game_id}' ---"
    )

    try:
        session: AsyncSession = g.session
        game_repo = GameRepository(session)
        auth_repo = AuthRepository(session)
        ws_manager = cast(WebSocketManager, current_app.ws_manager)  # type: ignore

        facade = GameFacade(game_repo, auth_repo, ws_manager)

        updated_game = await facade.join_game(game_id, current_user)

        game_data: Dict[str, Any] = {
            "game_id": updated_game.game_id,
            "white_player_id": updated_game.white_player_id,
            "black_player_id": updated_game.black_player_id,
            "status": updated_game.status.value,
            "created_at": updated_game.created_at.isoformat(),
            "updated_at": updated_game.updated_at.isoformat(),
        }

        response_dict, status_code = create_success_response(
            data=game_data, status_code=200
        )
        return jsonify(response_dict), status_code

    except Exception as e:

        logger.error(
            f"Unexpected error joining game for user {current_user.user_id}: {e}",
            exc_info=True,
        )
        response_dict, status_code = create_error_response("Internal Server Error", 500)
        return jsonify(response_dict), status_code


@game_bp.route("/<string:game_id>/", methods=["GET"])
@token_required
async def get_game_history(game_id: str, current_user: User):
    logger.debug(
        f"--- get_game_history: Request for game '{game_id}' from user '{current_user.username}' ---"
    )

    try:
        session: AsyncSession = g.session

        game_repo = GameRepository(session)

        ws_manager = cast(WebSocketManager, current_app.ws_manager)  # type: ignore
        facade = GameFacade(game_repo, AuthRepository(session), ws_manager)

        game_details = await facade.get_game_details(game_id, current_user)

        response, status = create_success_response(data=game_details, status_code=200)
        return jsonify(response), status

    except Exception as e:
        logger.error(
            f"Unexpected error getting game history for '{game_id}': {e}", exc_info=True
        )
        response, status = create_error_response(str(e), 500)
        return jsonify(response), status


@game_bp.route("/<string:game_id>/moves/", methods=["POST"])
@token_required
async def make_move_route(game_id: str, current_user: User):
    """
    Allows a player to make a move in an active game.
    """
    logger.debug(
        f"--- make_move: Request from user '{current_user.username}' for game '{game_id}' ---"
    )

    try:
        session = g.session
        game_repo = GameRepository(session)
        auth_repo = AuthRepository(session)

        ws_manager = cast(WebSocketManager, current_app.ws_manager)  # type: ignore
        facade = GameFacade(game_repo, auth_repo, ws_manager)

        json_data = await request.get_json()
        if not json_data or "move" not in json_data:
            raise ValidationError("Request body must include a 'move' field.")

        move_uci = json_data["move"]

        await facade.make_move(game_id, current_user, move_uci)

        response, status = create_success_response(
            data={"message": "Move successfully recorded"}, status_code=201
        )
        return jsonify(response), status

    except Exception as e:

        logger.error(
            f"Unexpected error making move in game {game_id}: {e}", exc_info=True
        )
        response, status = create_error_response("Internal Server Error", 500)
        return jsonify(response), status
