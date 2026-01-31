from typing import Any, Dict
from quart import Blueprint, jsonify, g, request

from app.auth.models import User
from app.auth.decorators import token_required
from app.auth.repository import AuthRepository
from app.auth.websocket_auth_facade import WebSocketAuthFacade
from app.common.response_utils import create_success_response, create_error_response
from app.common.schemas import MoveRequest
from app.extensions import redis_client
from pydantic import ValidationError as PydanticValidationError
from app.common.schemas import TakebackResponseRequest

# from app.game.models import Game
from app.dependency_injection import get_container
from app.logger_setup import get_logger
from .repository import GameRepository
from sqlalchemy.ext.asyncio import AsyncSession

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
        container = get_container(session)
        facade = container.get_game_facade()

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
        container = get_container(session)
        facade = container.get_game_facade()

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

        container = get_container(session)
        facade = container.get_game_facade()

        game_details = await facade.get_serialized_game_state(game_id)

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
        body = await request.get_json()
        # Automatic Regex validation for UCI format happens here!
        validated_data = MoveRequest(**body)
        move_uci = validated_data.move
        session = g.session
        container = get_container(session)
        facade = container.get_game_facade()

        await facade.make_move(game_id, current_user, move_uci)

        response, status = create_success_response(
            data={"message": "Move successfully recorded"}, status_code=201
        )
        return jsonify(response), status

    except PydanticValidationError as e:
        # Clean error handling for invalid input
        logger.warning(f"Validation failed: {e.errors()}")
        # We take the first error message to show the user
        msg = e.errors()[0]["msg"]
        field = e.errors()[0]["loc"][0]
        response_dict, status_code = create_error_response(
            f"Invalid {field}: {msg}", 400
        )
        return jsonify(response_dict), status_code

    except Exception as e:

        logger.error(
            f"Unexpected error making move in game {game_id}: {e}", exc_info=True
        )
        response, status = create_error_response("Internal Server Error", 500)
        return jsonify(response), status


@game_bp.route("/<string:game_id>/undo/", methods=["POST"])
@token_required
async def undo_move_route(game_id: str, current_user: User):
    """
    Beta Feature: Request a takeback (Undo last move).
    """
    try:
        session: AsyncSession = g.session
        container = get_container(session)
        facade = container.get_game_facade()

        await facade.undo_last_move(game_id, current_user)

        response, status = create_success_response(
            data={"message": "Undo successful"}, status_code=200
        )
        return jsonify(response), status

    except Exception as e:
        logger.error(f"Error undoing move: {e}", exc_info=True)
        response, status = create_error_response(str(e), 500)
        return jsonify(response), status


@game_bp.route("/<string:game_id>/takeback/request/", methods=["POST"])
@token_required
async def request_takeback_route(game_id: str, current_user: User):
    """
    Initiates a takeback request.
    """
    try:
        session: AsyncSession = g.session
        container = get_container(session)
        facade = container.get_game_facade()

        await facade.request_takeback(game_id, current_user)

        response, status = create_success_response(
            data={"message": "Takeback requested successfully"}, status_code=200
        )
        return jsonify(response), status

    except Exception as e:
        logger.error(f"Error requesting takeback: {e}", exc_info=True)
        # Map GameErrors to appropriate status codes if needed
        response, status = create_error_response(str(e), 500)
        return jsonify(response), status


@game_bp.route("/<string:game_id>/takeback/respond/", methods=["POST"])
@token_required
async def respond_takeback_route(game_id: str, current_user: User):
    """
    Accepts or declines a takeback request.
    Payload: {"accepted": true}
    """
    try:
        body = await request.get_json()

        validated_data = TakebackResponseRequest(**body)
        is_accepted = validated_data.accepted
        if is_accepted is None:  # type: ignore

            return (
                jsonify(
                    create_error_response("Missing 'accepted' boolean field", 500)[0]
                ),
                500,
            )

        session: AsyncSession = g.session
        container = get_container(session)
        facade = container.get_game_facade()

        await facade.respond_takeback(game_id, current_user, bool(is_accepted))

        action = "accepted" if is_accepted else "declined"
        response, status = create_success_response(
            data={"message": f"Takeback {action}"}, status_code=200
        )
        return jsonify(response), status

    except Exception as e:
        logger.error(f"Error responding to takeback: {e}", exc_info=True)
        response, status = create_error_response(str(e), 500)
        return jsonify(response), status


@game_bp.route("/<string:game_id>/signal/", methods=["POST"])
@token_required
async def signal_route(game_id: str, current_user: User):
    """
    Route for exchanging ephemeral signals (Video IDs, Chat messages).
    """
    try:
        body = await request.get_json()
        signal_type = body.get("type")
        payload = body.get("payload")

        if not signal_type or not payload:
            return jsonify({"error": "Missing type or payload"}), 400

        session: AsyncSession = g.session
        container = get_container(session)
        facade = container.get_game_facade()

        await facade.broadcast_signal(game_id, current_user, signal_type, payload)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Signal error: {e}", exc_info=True)
        response, status = create_error_response("Internal Server Error", 500)
        return jsonify(response), status


@game_bp.route("/<string:game_id>/chat/", methods=["POST"])
@token_required
async def send_chat_route(game_id: str, current_user: User):
    try:
        body = await request.get_json()
        content = body.get("content")

        if not content or not isinstance(content, str) or not content.strip():
            return jsonify({"error": "Message cannot be empty"}), 400

        session: AsyncSession = g.session
        container = get_container(session)
        facade = container.get_game_facade()

        await facade.send_chat_message(game_id, current_user, content)

        return jsonify({"status": "sent"}), 201

    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500
