from typing import Any, Dict, List, Protocol, Tuple

from app.logger_setup import get_logger
from app.managers.game_manager import GameWebSocketManager

logger = get_logger(__name__)


class EventPublisher(Protocol):
    """What commands need to announce a game event. Implemented by
    GameWebSocketManager (publishes immediately) and DeferredEventPublisher."""

    async def publish_event(self, game_id: str, payload: Dict[str, Any]) -> None: ...


class DeferredEventPublisher:
    """
    Per-request outbox: commands queue their events here instead of publishing
    them straight away. After the request's transaction commits, flush() hands
    them to the WebSocket manager in order; on rollback they are discarded.

    This way clients never see a move/resign/chat that was rolled back.
    """

    def __init__(self, ws_manager: GameWebSocketManager):
        self._ws_manager = ws_manager
        self._pending: List[Tuple[str, Dict[str, Any]]] = []

    async def publish_event(self, game_id: str, payload: Dict[str, Any]) -> None:
        self._pending.append((game_id, payload))

    async def flush(self) -> None:
        pending, self._pending = self._pending, []
        for game_id, payload in pending:
            try:
                await self._ws_manager.publish_event(game_id, payload)
            except Exception as e:
                # The state is already committed; a lost broadcast is repaired
                # by the client's next full sync (reconnect / GET game).
                logger.error(
                    f"Publishing '{payload.get('type')}' for game '{game_id}' "
                    f"failed after commit: {e}",
                    exc_info=True,
                )

    def discard(self) -> None:
        if self._pending:
            logger.info(f"Discarded {len(self._pending)} event(s) after rollback")
        self._pending = []
