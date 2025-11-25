import json
from typing import Any, Dict
from quart.wrappers import Websocket
from app.managers.base import BaseWebSocketManager


class GameWebSocketManager(BaseWebSocketManager):
    """
    Refined Abstraction for Chess Games.
    """

    def _get_channel_name(self, game_id: str) -> str:
        return f"game:{game_id}"

    async def connect_to_game(self, game_id: str, websocket: Websocket):
        """Called by the WebSocket Route"""
        channel = self._get_channel_name(game_id)
        await self.connect(channel, websocket)

    async def disconnect_from_game(self, game_id: str, websocket: Websocket):
        """Called by the WebSocket Route cleanup"""
        channel = self._get_channel_name(game_id)
        await self.disconnect(channel, websocket)

    async def publish_event(self, game_id: str, payload: Dict[str, Any]):
        """Called by GameFacade"""

        channel = self._get_channel_name(game_id)
        message_str = json.dumps(payload)
        await self.provider.publish(channel, message_str)
