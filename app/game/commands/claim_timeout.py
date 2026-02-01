from datetime import datetime, timezone
from app.game.commands.base import IGameCommand
from app.game.repository import GameRepository
from app.managers.game_manager import GameWebSocketManager
from app.game.models import Game, GameStatus
from app.game.serializers import build_websocket_payload
from app.logger_setup import get_logger

logger = get_logger(__name__)


class ClaimTimeoutCommand(IGameCommand):
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
        logger.info(f"Checking timeout claim for game {self.game.game_id}")

        if self.game.status != GameStatus.ACTIVE:
            return  # Game already over

        # --- OPTIMIZATION START ---
        # Example: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

        fen_parts = self.game.current_fen.split(" ")
        if len(fen_parts) < 2:
            logger.error(
                f"Corrupted FEN in DB for game {self.game.game_id}: {self.game.current_fen}"
            )
            return

        active_color_char = fen_parts[1]  # 'w' or 'b'
        is_white_turn = active_color_char == "w"

        if not self.game.last_move_at:

            return

        now = datetime.now(timezone.utc)
        elapsed_delta = now - self.game.last_move_at
        elapsed_ms = int(elapsed_delta.total_seconds() * 1000)

        # Default 3 mins if None (shouldn't happen in active)
        current_white_ms = (
            self.game.white_time_ms if self.game.white_time_ms is not None else 180000
        )
        current_black_ms = (
            self.game.black_time_ms if self.game.black_time_ms is not None else 180000
        )

        is_flag_fall = False
        winner_status = None

        if is_white_turn:
            # White is thinking... did their time run out?
            remaining = current_white_ms - elapsed_ms
            if remaining <= 0:
                is_flag_fall = True
                winner_status = GameStatus.BLACK_WIN
                self.game.white_time_ms = 0  # Clamp to 0
        else:
            # Black is thinking... did their time run out?
            remaining = current_black_ms - elapsed_ms
            if remaining <= 0:
                is_flag_fall = True
                winner_status = GameStatus.WHITE_WIN
                self.game.black_time_ms = 0  # Clamp to 0

        if is_flag_fall and winner_status:
            # 1. Update DB Status
            self.game.status = winner_status
            await self.game_repo.save_game(self.game)

            # 2. Broadcast Game Over
            # We fetch the latest move just for the serializer structure
            latest_move = await self.game_repo.get_latest_move(self.game.game_id)

            payload = build_websocket_payload(self.game, latest_move)
            payload["data"]["game_over_reason"] = "timeout"

            await self.ws_manager.publish_event(self.game.game_id, payload)
            logger.info(f"Timeout confirmed. Game {self.game.game_id} ended.")
        else:
            logger.debug("Claim timeout rejected: Time has not run out on server yet.")
