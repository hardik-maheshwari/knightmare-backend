from app.game.commands.base import IGameCommand
from app.game.repository import GameRepository
from app.game.serializers import build_takeback_offer_payload
from app.managers.game_manager import GameWebSocketManager
from app.game.models import Game
from app.auth.models import User
from app.game.exceptions import GameError
from app.logger_setup import get_logger

logger = get_logger(__name__)


class RequestTakebackCommand(IGameCommand):
    def __init__(
        self,
        game: Game,
        requester: User,
        game_repo: GameRepository,
        ws_manager: GameWebSocketManager,
    ):
        self.game = game
        self.requester = requester
        self.game_repo = game_repo
        self.ws_manager = ws_manager

    async def execute(self) -> None:
        logger.info(
            f"User {self.requester.username} requesting takeback in game {self.game.game_id}"
        )

        
        if self.game.takeback_requester_id is not None:

            if self.game.takeback_requester_id == self.requester.user_id:
                return
            else:
                raise GameError(
                    "A takeback request is already pending from the other player."
                )

        latest_move = await self.game_repo.get_latest_move(self.game.game_id)
        if not latest_move:
            raise GameError("Cannot request takeback: No moves have been made.")

        self.game.takeback_requester_id = self.requester.user_id

        # Note: We must save the game to persist this flag
        await self.game_repo.save_game(self.game)

        # 3. Broadcast
        # We send a special event so the frontend knows to show the "Accept/Decline" modal
        payload = build_takeback_offer_payload(self.game.game_id, self.requester)
        await self.ws_manager.publish_event(self.game.game_id, payload)
