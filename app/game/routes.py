from typing import Any, Dict
from quart import Blueprint, jsonify, g, request

from app.auth.models import User
from app.auth.decorators import token_required
from app.common.exceptions import ValidationError
from app.common.response_utils import create_success_response
from app.common.schemas import MoveRequest, TakebackResponseRequest
from app.dependency_injection import get_container
from app.game.facade import GameFacade
from app.game.models import Game
from app.logger_setup import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

# Errors are not caught here: domain exceptions propagate to app/errors.py, which
# maps them to 400/403/404/409 (unexpected ones to 500), and any error response
# rolls back the request's DB session.

game_bp = Blueprint("game", __name__, url_prefix="/api/games")

logger = get_logger(__name__)

MAX_CHAT_LENGTH = 500  # matches the frontend input's maxLength


def _game_facade() -> GameFacade:
    session: AsyncSession = g.session
    return get_container(session).get_game_facade()


async def _json_body() -> Dict[str, Any]:
    """Request JSON as a dict; missing or malformed bodies become {}."""
    body = await request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _game_summary(game: Game) -> Dict[str, Any]:
    return {
        "game_id": game.game_id,
        "white_player_id": game.white_player_id,
        "black_player_id": game.black_player_id,
        "status": game.status.value,
        "created_at": game.created_at.isoformat(),
        "updated_at": game.updated_at.isoformat(),
    }


@game_bp.route("/<string:game_id>/ws-ticket/", methods=["POST"])
@token_required
async def get_websocket_ticket(game_id: str, current_user: User):
    """
    Generates a short-lived, single-use ticket for authenticating a WebSocket
    connection to THIS game.
    """
    session: AsyncSession = g.session
    ws_auth_service = get_container(session).get_ws_auth_facade()

    ticket = await ws_auth_service.issue_ticket(game_id, current_user)

    response, status = create_success_response(data={"ticket": ticket})
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
    new_game = await _game_facade().create_game(creator=current_user)

    logger.info(
        f"Game {new_game.game_id} created successfully for user {current_user.username}."
    )
    response_data, status_code = create_success_response(
        data=_game_summary(new_game), status_code=201
    )
    return jsonify(response_data), status_code


@game_bp.route("/<string:game_id>/join/", methods=["POST"])
@token_required
async def join_game_route(game_id: str, current_user: User):
    """
    Allows the current user to join an existing game that is waiting for an opponent.
    """
    logger.debug(
        f"--- join_game: Request received from user '{current_user.username}' for game '{game_id}' ---"
    )
    updated_game = await _game_facade().join_game(game_id, current_user)

    response_dict, status_code = create_success_response(
        data=_game_summary(updated_game), status_code=200
    )
    return jsonify(response_dict), status_code


@game_bp.route("/<string:game_id>/", methods=["GET"])
@token_required
async def get_game_history(game_id: str, current_user: User):
    logger.debug(
        f"--- get_game_history: Request for game '{game_id}' from user '{current_user.username}' ---"
    )
    game_details = await _game_facade().get_serialized_game_state(game_id)

    response, status = create_success_response(data=game_details, status_code=200)
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
    # Regex validation for UCI format happens here (PydanticValidationError -> 400).
    validated_data = MoveRequest.model_validate(await _json_body())

    await _game_facade().make_move(game_id, current_user, validated_data.move)

    response, status = create_success_response(
        data={"message": "Move successfully recorded"}, status_code=201
    )
    return jsonify(response), status


@game_bp.route("/<string:game_id>/undo/", methods=["POST"])
@token_required
async def undo_move_route(game_id: str, current_user: User):
    """
    Beta Feature: Request a takeback (Undo last move).
    """
    await _game_facade().undo_last_move(game_id, current_user)

    response, status = create_success_response(
        data={"message": "Undo successful"}, status_code=200
    )
    return jsonify(response), status


@game_bp.route("/<string:game_id>/takeback/request/", methods=["POST"])
@token_required
async def request_takeback_route(game_id: str, current_user: User):
    """
    Initiates a takeback request.
    """
    await _game_facade().request_takeback(game_id, current_user)

    response, status = create_success_response(
        data={"message": "Takeback requested successfully"}, status_code=200
    )
    return jsonify(response), status


@game_bp.route("/<string:game_id>/takeback/respond/", methods=["POST"])
@token_required
async def respond_takeback_route(game_id: str, current_user: User):
    """
    Accepts or declines a takeback request.
    Payload: {"accepted": true}
    """
    validated_data = TakebackResponseRequest.model_validate(await _json_body())
    is_accepted = validated_data.accepted

    await _game_facade().respond_takeback(game_id, current_user, is_accepted)

    action = "accepted" if is_accepted else "declined"
    response, status = create_success_response(
        data={"message": f"Takeback {action}"}, status_code=200
    )
    return jsonify(response), status


@game_bp.route("/<string:game_id>/signal/", methods=["POST"])
@token_required
async def signal_route(game_id: str, current_user: User):
    """
    Route for exchanging ephemeral WebRTC signals (video peer IDs).
    Only the two players of the game may send signals.
    """
    body = await _json_body()
    signal_type = body.get("type")
    payload = body.get("payload")

    if not signal_type or not payload:
        raise ValidationError("Missing type or payload")

    await _game_facade().broadcast_signal(game_id, current_user, signal_type, payload)

    return jsonify({"status": "ok"}), 200


@game_bp.route("/<string:game_id>/chat/", methods=["POST"])
@token_required
async def send_chat_route(game_id: str, current_user: User):
    """
    Sends a chat message. Only the two players of the game may chat.
    """
    content = (await _json_body()).get("content")

    if not isinstance(content, str) or not content.strip():
        raise ValidationError("Message cannot be empty")
    if len(content) > MAX_CHAT_LENGTH:
        raise ValidationError(
            f"Message is too long (max {MAX_CHAT_LENGTH} characters)"
        )

    await _game_facade().send_chat_message(game_id, current_user, content)

    return jsonify({"status": "sent"}), 201


@game_bp.route("/<string:game_id>/resign/", methods=["POST"])
@token_required
async def resign_game_route(game_id: str, current_user: User):
    await _game_facade().resign_game(game_id, current_user)

    response, status = create_success_response(
        data={"message": "You have resigned."}, status_code=200
    )
    return jsonify(response), status


@game_bp.route("/<string:game_id>/claim-timeout/", methods=["POST"])
@token_required
async def claim_timeout_route(game_id: str, current_user: User):
    await _game_facade().claim_timeout(game_id)

    # We don't really need to return data, the WebSocket will handle the UI update
    return jsonify({"status": "checked"}), 200
