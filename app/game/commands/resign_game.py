from app.game.commands.base import IGameCommand
from app.game.repository import GameRepository
from app.managers.game_manager import GameWebSocketManager
from app.game.models import Game, GameStatus
from app.auth.models import User
from app.game.exceptions import GameError
from app.game.serializers import build_websocket_payload
from app.logger_setup import get_logger

logger = get_logger(__name__)


class ResignGameCommand(IGameCommand):
    def __init__(
        self,
        game: Game,
        player: User,
        game_repo: GameRepository,
        ws_manager: GameWebSocketManager,
    ):
        self.game = game
        self.player = player
        self.game_repo = game_repo
        self.ws_manager = ws_manager

    async def execute(self) -> None:
        logger.info(
            f"User {self.player.username} is resigning game {self.game.game_id}"
        )

        if self.game.status != GameStatus.ACTIVE:
            raise GameError("Cannot resign a game that is not active.")

        # Determine who wins based on who resigned
        if self.player.user_id == self.game.white_player_id:
            self.game.status = GameStatus.BLACK_WIN
            winner = "Black"
        elif self.player.user_id == self.game.black_player_id:
            self.game.status = GameStatus.WHITE_WIN
            winner = "White"
        else:
            raise GameError("User is not a player in this game.")

        # Save DB
        await self.game_repo.save_game(self.game)

        # Broadcast update
        # We fetch the latest move just to satisfy the serializer payload requirements
        latest_move = await self.game_repo.get_latest_move(self.game.game_id)

        payload = build_websocket_payload(self.game, latest_move)
        # Add a custom flag so frontend knows exactly why game ended
        payload["data"]["game_over_reason"] = "resignation"

        await self.ws_manager.publish_event(self.game.game_id, payload)
        logger.info(f"Game {self.game.game_id} ended. {winner} wins by resignation.")
