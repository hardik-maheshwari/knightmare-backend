from typing import Any, Dict, Optional

import chess
from app.auth.models import User
from app.game.models import Game, GameStatus, Move


def build_websocket_payload(game: Game, latest_move: Optional[Move]) -> Dict[str, Any]:
    """
    Lightweight serializer for broadcasts.
    O(1) Complexity. Uses game.current_fen and avoids fetching history.

    latest_move is None when no moves exist yet (resign/timeout before the first
    move, or undoing the only move).
    """
    # We use the stored FEN to create the board object instantly
    board = chess.Board(game.current_fen)

    white_player_data = None
    if game.white_player:
        white_player_data = {
            "id": game.white_player.user_id,
            "username": game.white_player.username,
        }

    black_player_data = None
    if game.black_player:
        black_player_data = {
            "id": game.black_player.user_id,
            "username": game.black_player.username,
        }

    return {
        "type": "game_update",
        "data": {
            "game_id": game.game_id,
            "white_player": white_player_data,
            "black_player": black_player_data,
            "status": game.status.value,
            "current_fen": game.current_fen,  # Use the column!
            "turn": "w" if board.turn == chess.WHITE else "b",
            "is_check": board.is_check(),
            "is_checkmate": board.is_checkmate(),
            "is_draw": game.status == GameStatus.DRAW,
            # OPTIMIZATION: We only send the latest move, not the whole list.
            # The frontend should append this to its local list.
            "last_move": latest_move.move_notation if latest_move else None,
            "moves": [],  # We send empty list or remove it to signal "no history sent"
            "white_time_ms": game.white_time_ms,
            "black_time_ms": game.black_time_ms,
            "last_move_at": (
                game.last_move_at.isoformat() if game.last_move_at else None
            ),
        },
    }


def build_takeback_offer_payload(game_id: str, requester: User) -> Dict[str, Any]:
    return {
        "type": "takeback_offered",
        "data": {
            "game_id": game_id,
            "requester_id": requester.user_id,
            "requester_username": requester.username,
        },
    }


def build_takeback_response_payload(game_id: str, status: str) -> Dict[str, Any]:
    """
    Status should be 'accepted' or 'declined'.
    """
    return {"type": "takeback_response", "data": {"game_id": game_id, "status": status}}
