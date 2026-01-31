from app.game.commands.base import IGameCommand
from app.game.models import ChatMessage
from app.auth.models import User
from app.managers.game_manager import GameWebSocketManager
from app.game.repository import GameRepository
from typing import Any, Dict

class SendChatCommand(IGameCommand):
    def __init__(
        self,
        game_id: str,
        sender: User,
        content: str,
        game_repo: GameRepository,
        ws_manager: GameWebSocketManager,
    ):
        self.game_id = game_id
        self.sender = sender
        self.content = content
        self.game_repo = game_repo
        self.ws_manager = ws_manager

    async def execute(self) -> None:
        # 1. Persist
        new_msg = ChatMessage(
            game_id=self.game_id,
            sender_id=self.sender.user_id,
            content=self.content
        )
        saved_msg = await self.game_repo.save_chat_message(new_msg)

        # 2. Broadcast
        payload: Dict[str, Any] = {
            "type": "chat_message",
            "data": {
                "message_id": saved_msg.message_id,
                "sender_username": self.sender.username,
                "content": self.content,
                "timestamp": saved_msg.created_at.isoformat(),
            },
        }
        await self.ws_manager.publish_event(self.game_id, payload)