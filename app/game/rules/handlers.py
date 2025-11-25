from typing import cast
import chess
from app.auth.models import User
from app.game.exceptions import MoveNotPossibleError, UserNotPlayerError
from app.game.models import Game, GameStatus
from .base import GameRuleHandler
from .context import MoveContext
from app.logger_setup import get_logger

logger = get_logger(__name__)


class GameActiveRule(GameRuleHandler):
    def check(self, move_context: MoveContext) -> None:
        game_obj = cast(Game, move_context.game)

        if game_obj.status != GameStatus.ACTIVE:

            raise MoveNotPossibleError(
                f"Game is not active. Status: {game_obj.status.value}"
            )
        super().check(move_context)


class PlayerAuthRule(GameRuleHandler):
    def check(self, move_context: MoveContext) -> None:
        player_obj = cast(User, move_context.player)
        game_obj = cast(Game, move_context.game)
        if player_obj.user_id not in (
            game_obj.white_player_id,
            game_obj.black_player_id,
        ):
            raise UserNotPlayerError("You are not a player in this game.")
        super().check(move_context)


class TurnRule(GameRuleHandler):
    def check(self, move_context: MoveContext) -> None:
        is_whites_turn = move_context.board.turn == chess.WHITE
        player_obj = cast(User, move_context.player)
        game_obj = cast(Game, move_context.game)

        # Check if player owns the color for the current turn
        if is_whites_turn and player_obj.user_id != game_obj.white_player_id:
            raise MoveNotPossibleError("It is not your turn (White's turn).")

        if not is_whites_turn and player_obj.user_id != game_obj.black_player_id:
            raise MoveNotPossibleError("It is not your turn (Black's turn).")

        super().check(move_context)


class LegalMoveRule(GameRuleHandler):
    def check(self, move_context: MoveContext) -> None:
        try:
            # 1. Parse
            move_obj = chess.Move.from_uci(move_context.move_uci)

            # 2. Validate Logic
            if move_obj not in move_context.board.legal_moves:
                raise MoveNotPossibleError("Move is illegal according to chess rules.")

            # 3. Enrich Context (Optimization)
            # We store this so the Facade doesn't have to re-parse it later.
            move_context.parsed_move = move_obj

        except ValueError:
            raise MoveNotPossibleError(f"Invalid move format: {move_context.move_uci}")

        super().check(move_context)
