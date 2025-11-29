import chess
from app.game.commands.base import IGameCommand
from app.game.repository import GameRepository
from app.game.serializers import build_websocket_payload
from app.managers.game_manager import GameWebSocketManager
from app.game.models import Game, GameStatus
from app.game.exceptions import GameError
from app.logger_setup import get_logger

logger = get_logger(__name__)


class UndoLastMoveCommand(IGameCommand):
    def __init__(
        self,
        game: Game,
        game_repo: GameRepository,
        ws_manager: GameWebSocketManager,
    ):
        self.game = game
        self.game_repo = game_repo
        self.ws_manager = ws_manager

    async def execute(self) -> None:
        logger.info(f"Executing Undo/Takeback for game {self.game.game_id}")

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

        # If the game ended (Checkmate/Draw), undoing MUST revive it.
        if self.game.status != GameStatus.ACTIVE:
            self.game.status = GameStatus.ACTIVE
            logger.info(f"Game {self.game.game_id} revived to ACTIVE status.")

        ws_payload = build_websocket_payload(self.game, previous_move)
        await self.ws_manager.publish_event(self.game.game_id, ws_payload)

    