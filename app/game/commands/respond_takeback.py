from app.game.commands.base import IGameCommand
from app.game.commands.undo_move import UndoLastMoveCommand
from app.game.repository import GameRepository
from app.managers.publisher import EventPublisher
from app.game.models import Game
from app.auth.models import User
from app.game.exceptions import GameError
from app.game.serializers import build_takeback_response_payload
from app.logger_setup import get_logger

logger = get_logger(__name__)

class RespondTakebackCommand(IGameCommand):
    def __init__(
        self,
        game: Game,
        responder: User,
        is_accepted: bool,
        game_repo: GameRepository,
        ws_manager: EventPublisher,
    ):
        self.game = game
        self.responder = responder
        self.is_accepted = is_accepted
        self.game_repo = game_repo
        self.ws_manager = ws_manager

    async def execute(self) -> None:
        logger.info(f"User {self.responder.username} responding to takeback: {self.is_accepted}")

        requester_id = self.game.takeback_requester_id

        # 1. Validation
        if requester_id is None:
            raise GameError("No pending takeback request to respond to.")

        if self.responder.user_id == requester_id:
            raise GameError("You cannot respond to your own takeback request.")

        # 2. Clear the Flag (Regardless of decision)
        self.game.takeback_requester_id = None
        # We save the cleared flag state
        await self.game_repo.save_game(self.game)

        # 3. Branching Logic
        if self.is_accepted:
            # --- DELEGATION ---
            logger.info("Takeback ACCEPTED. Executing Undo Command.")
            undo_cmd = UndoLastMoveCommand(self.game, self.game_repo, self.ws_manager)
            await undo_cmd.execute()
            
            # Broadcast specific "Accepted" event (UI might show a success toast)
            # Note: undo_cmd already broadcasted the board update. 
            # This additional event is just for UI feedback.
            payload = build_takeback_response_payload(self.game.game_id, status="accepted")
            await self.ws_manager.publish_event(self.game.game_id, payload)
            
        else:
            logger.info("Takeback DECLINED.")
            # Broadcast "Declined" event (UI shows error toast to requester)
            payload = build_takeback_response_payload(self.game.game_id, status="declined")
            await self.ws_manager.publish_event(self.game.game_id, payload)