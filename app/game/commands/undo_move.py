from datetime import datetime, timezone

import chess
from app.game.commands.base import IGameCommand
from app.game.repository import GameRepository
from app.game.serializers import build_websocket_payload
from app.managers.publisher import EventPublisher
from app.game.models import Game, GameStatus
from app.game.exceptions import GameError
from app.logger_setup import get_logger

logger = get_logger(__name__)


class UndoLastMoveCommand(IGameCommand):
    def __init__(
        self,
        game: Game,
        game_repo: GameRepository,
        ws_manager: EventPublisher,
    ):
        self.game = game
        self.game_repo = game_repo
        self.ws_manager = ws_manager

    def _ended_on_the_board(self) -> bool:
        """True if the game was ended by its last move (checkmate or a draw)."""
        if self.game.status == GameStatus.DRAW:
            return True
        if self.game.status in (GameStatus.WHITE_WIN, GameStatus.BLACK_WIN):
            return chess.Board(self.game.current_fen).is_checkmate()
        return False

    async def execute(self) -> None:
        logger.info(f"Executing Undo/Takeback for game {self.game.game_id}")

        if self.game.status != GameStatus.ACTIVE and not self._ended_on_the_board():
            # Resignation / timeout / not started: undoing a move can't change
            # that result, so it must not revive the game.
            raise GameError(
                f"Cannot undo: game is not active (status: {self.game.status.value})."
            )

        move_to_undo = await self.game_repo.get_latest_move(self.game.game_id)

        if not move_to_undo:
            raise GameError("Cannot undo: No moves have been made yet.")

        await self.game_repo.delete_move(move_to_undo)

        previous_move = await self.game_repo.get_latest_move(self.game.game_id)

        if previous_move:

            target_fen = previous_move.board_fen_after_move
        else:
            # No previous moves? We are back at the start.
            target_fen = chess.STARTING_FEN

        # 4. Mutate Game State
        self.game.current_fen = target_fen

        # If the last move ended the game (checkmate/draw), undoing it revives it.
        if self.game.status != GameStatus.ACTIVE:
            self.game.status = GameStatus.ACTIVE
            logger.info(f"Game {self.game.game_id} revived to ACTIVE status.")

        # Any pending offer is resolved by this undo. Restart the clock for the
        # side now to move (banked times are not refunded).
        self.game.takeback_requester_id = None
        self.game.last_move_at = datetime.now(timezone.utc)

        ws_payload = build_websocket_payload(self.game, previous_move)
        await self.ws_manager.publish_event(self.game.game_id, ws_payload)

    