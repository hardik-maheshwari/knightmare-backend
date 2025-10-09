import asyncio
import secrets
from typing import Any, Dict, List, cast
import chess
from quart import Blueprint, current_app, jsonify, g, request, websocket
from app.auth.exceptions import InvalidCredentialsError, UserNotFoundError
from app.auth.models import User
from app.auth.decorators import token_required
from app.auth.repository import AuthRepository
from app.common.exceptions import ValidationError
from app.common.response_utils import create_success_response, create_error_response
from app.game.exceptions import (
    AlreadyInGameError,
    GameNotFoundError,
    GameNotJoinableError,
    MoveNotPossibleError,
    UserNotPlayerError,
)
from app.extensions import AsyncSessionLocal, redis_client

# from app.game.models import Game
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
        repo = GameRepository(session)

        game = await repo.get_game_by_id(game_id)
        if not game:
            raise GameNotFoundError()

        is_player = (
            current_user.user_id == game.white_player_id
            or current_user.user_id == game.black_player_id
        )

        if not is_player:
            logger.warning(
                f"FORBIDDEN: User '{current_user.username}' attempted to access game '{game_id}' without permission."
            )

            raise UserNotPlayerError()

        ticket = secrets.token_urlsafe(24)

        await redis_client.setex(f"ws_ticket:{ticket}", 15, current_user.user_id)

        logger.info(
            f"Issued WebSocket ticket for user '{current_user.username}' for game '{game_id}'."
        )
        response, status = create_success_response(data={"ticket": ticket})
        return jsonify(response), status

    except GameNotFoundError as e:
        logger.warning(f"Join failed: Game '{game_id}' not found.")
        response, status = create_error_response(str(e), 404)
        return jsonify(response), status

    except UserNotFoundError as e:
        logger.warning(
            f"FORBIDDEN: User '{current_user.username}' attempted to access game '{game_id}'. Reason: {e}"
        )
        response, status = create_error_response(str(e), 403)
        return jsonify(response), status


@game_bp.websocket("/<string:game_id>/ws")
async def game_websocket(game_id: str):
    """
    Handles the websocket connection for a specific game.
    Authenticates user via a token in the query string.
    """

    logger.info(f"--- WebSocket connection attempt for game '{game_id}' ---")
    logger.debug(f"Request args: {websocket.args}")

    async with AsyncSessionLocal() as session:
        logger.info(
            "New DB session created specifically for this WebSocket connection."
        )

        repo = GameRepository(session)
        auth_repo = AuthRepository(session)
        ws_manager = cast(WebSocketManager, current_app.ws_manager)  # type: ignore
        current_user: User | None = None

        try:

            ticket_from_url = websocket.args.get("ticket")
            redis_key = f"ws_ticket:{ticket_from_url}"

            byte_user_id_from_redis = await redis_client.get(redis_key)

            if byte_user_id_from_redis is None:
                raise InvalidCredentialsError()

            await redis_client.delete(redis_key)

            user_id = int(byte_user_id_from_redis)

            current_user = await auth_repo.get_user_by_id_with_cache(user_id)

            if not isinstance(current_user, User):
                raise InvalidCredentialsError()

            logger.info(
                f"WS connection for user '{current_user.username}' to game '{game_id}' authenticated."
            )

            game = await repo.get_game_by_id(game_id)
            if not game:
                logger.warning(f"WS connection rejected: Game '{game_id}' not found.")
                await websocket.close(1011, "Game not found")
                return

            await ws_manager.connect(game_id, websocket._get_current_object()) # type: ignore

            await ws_manager.broadcast_game_state(game_id)

            while True:
                try:

                    await websocket.receive()
                except asyncio.CancelledError:
                    # This happens on a clean disconnect
                    logger.info(
                        f"WS connection for '{current_user.username}' cancelled."
                    )
                    break

        except InvalidCredentialsError as e:
            logger.warning(f"WS auth failed for game '{game_id}': {e}")
            await websocket.close(1008, "Invalid or expired token")
            return

        except Exception as e:
            logger.error(
                f"Unexpected error in websocket for game '{game_id}': {e}",
                exc_info=True,
            )
            # Ensure the socket is closed on any unexpected error
            await websocket.close(1011, "Internal server error")

        finally:

            if current_user:
                logger.info(
                    f"Disconnecting user '{current_user.username}' from game '{game_id}'."
                )
            await ws_manager.disconnect(game_id, websocket)
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
        repo = GameRepository(session)

        new_game = await repo.create_game(creator=current_user)

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

        updated_game = await game_repo.join_game(game_id, current_user)

        game_data: Dict[str, Any] = {
            "game_id": updated_game.game_id,
            "white_player_id": updated_game.white_player_id,
            "black_player_id": updated_game.black_player_id,
            "status": updated_game.status.value,
            "created_at": updated_game.created_at.isoformat(),
            "updated_at": updated_game.updated_at.isoformat(),
        }

        rich_event_payload = await game_repo.get_serialized_game_state(
            game_id, auth_repo
        )

        if not rich_event_payload:
            raise GameNotFoundError("Game state could not be retrieved after move.")

        ws_manager = cast(WebSocketManager, current_app.ws_manager)  # type: ignore
        await ws_manager.publish_event(game_id, rich_event_payload)

        response_dict, status_code = create_success_response(
            data=game_data, status_code=200
        )
        return jsonify(response_dict), status_code

    except GameNotFoundError as e:
        logger.warning(f"Join failed: Game '{game_id}' not found.")
        response, status = create_error_response(str(e), 404)
        return jsonify(response), status

    except (GameNotJoinableError, AlreadyInGameError) as e:
        logger.warning(
            f"Join failed for user '{current_user.username}' in game '{game_id}': {e}"
        )
        response, status = create_error_response(str(e), 409)
        return jsonify(response), status

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
        repo = GameRepository(session)

        game = await repo.get_game_by_id(game_id)
        if not game:
            raise GameNotFoundError()

        is_player = (
            current_user.user_id == game.white_player_id
            or current_user.user_id == game.black_player_id
        )

        if not is_player:
            logger.warning(
                f"FORBIDDEN: User '{current_user.username}' attempted to access game '{game_id}' without permission."
            )
            # Return a 403 Forbidden error.
            raise UserNotPlayerError()

        moves = await repo.get_moves_for_game(game_id)

        current_fen = ""
        if not moves:

            current_fen = chess.STARTING_FEN
        else:
            latest_move = moves[-1]
            current_fen = latest_move.board_fen_after_move

        board = chess.Board(current_fen)
        is_whites_turn = board.turn == chess.WHITE

        turn = "w" if is_whites_turn else "b"

        serializable_moves: List[Dict[str, Any]] = [
            {
                "move_id": move.move_id,
                "move_number": move.move_number,
                "player_color": move.player_color.value,
                "move_notation": move.move_notation,
                "created_at": move.created_at.isoformat(),
            }
            for move in moves
        ]

        response_data: Dict[str, Any] = {
            "game_id": game_id,
            "white_player_id": game.white_player_id,
            "black_player_id": game.black_player_id,
            "status": game.status.value,
            "current_fen": current_fen,
            "turn": turn,
            "moves": serializable_moves,
        }

        response, status = create_success_response(data=response_data, status_code=200)
        return jsonify(response), status

    except GameNotFoundError as e:
        logger.warning(f"Game not found for ID '{game_id}': {e}")
        response, status = create_error_response(str(e), 400)
        return jsonify(response), status

    except UserNotPlayerError as e:
        logger.warning(
            f"FORBIDDEN: User '{current_user.username}' attempted to access game '{game_id}'. Reason: {e}"
        )
        response, status = create_error_response(str(e), 403)
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

        json_data = await request.get_json()
        if not json_data or "move" not in json_data:
            raise ValidationError("Request body must include a 'move' field.")

        move_uci = json_data["move"]

        await game_repo.make_move(game_id, current_user, move_uci)

        rich_event_payload = await game_repo.get_serialized_game_state(
            game_id, auth_repo
        )

        if not rich_event_payload:
            raise GameNotFoundError("Game state could not be retrieved after move.")

        ws_manager = cast(WebSocketManager, current_app.ws_manager)  # type: ignore
        await ws_manager.publish_event(game_id, rich_event_payload)

        response, status = create_success_response(
            data={"message": "Move successfully recorded"}, status_code=201
        )
        return jsonify(response), status

    except ValidationError as e:

        logger.warning(f"Move validation failed for game '{game_id}': {e}")

        response, status = create_error_response(str(e), 400)
        return jsonify(response), status

    except GameNotFoundError as e:

        logger.warning(
            f"Move failed: User '{current_user.username}' requested non-existent game '{game_id}'."
        )

        response, status = create_error_response(str(e), 404)
        return jsonify(response), status

    except MoveNotPossibleError as e:

        logger.warning(
            f"Illegal move rejected for user '{current_user.username}' in game '{game_id}': {e}"
        )

        response, status = create_error_response(str(e), 409)
        return jsonify(response), status

    except Exception as e:

        logger.error(
            f"Unexpected error making move in game {game_id}: {e}", exc_info=True
        )
        response, status = create_error_response("Internal Server Error", 500)
        return jsonify(response), status
