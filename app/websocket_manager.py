import asyncio
import json
from collections import defaultdict
from typing import Any, Optional, Set, Dict, TypedDict, cast

from quart.wrappers import Websocket
from redis.asyncio.client import PubSub
from app.auth.repository import AuthRepository
from app.extensions import AsyncSessionLocal, redis_client
from app.game.repository import GameRepository
from app.logger_setup import get_logger

logger = get_logger(__name__)


class RedisPubSubMessage(TypedDict):
    type: str
    channel: bytes
    pattern: Optional[bytes]
    data: bytes


class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts for chess games using Redis Pub/Sub
    for multi-process scalability.
    """

    def __init__(self):

        self._local_connections: Dict[str, Set[Websocket]] = defaultdict(set)

        self.redis_client = redis_client
        self.pubsub: PubSub = self.redis_client.pubsub()  # type: ignore
        self._subscribed_games: Set[str] = set()

        self.listener_task: asyncio.Task[None] | None = None
        logger.info(
            "WebSocketManager initialized with Redis Pub/Sub and listener task."
        )

    async def startup(self):
        """
        Starts the background Redis listener task. This should be called once
        when the application starts.
        """
        if self.listener_task is None:
            self.listener_task = asyncio.create_task(self._redis_listener())
            logger.info("WebSocketManager background listener task has been started.")
        else:
            logger.warning(
                "Startup called on WebSocketManager, but listener task is already running."
            )

    async def _redis_listener(self):
        """A perpetual background task that listens for published game events."""
        logger.info("Redis listener task started.")
        while True:
            if self._subscribed_games:
                try:
                    # 1. Wait for a message from a subscribed channel
                    message = cast(
                        Optional[RedisPubSubMessage],
                        await self.pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0
                        ),
                    )

                    # 2. Check if the message is a real event
                    if message and message.get("type") == "message":

                        # The 'data' from Redis is our rich JSON payload (as bytes)
                        message_json = message["data"]

                        # Get the game_id from the channel name (e.g., 'game:XYZ' -> 'XYZ')
                        channel_str = message["channel"]
                        game_id = channel_str.split(":", 1)[1]

                        logger.debug(
                            f"Received pub/sub event for game '{game_id}'. Broadcasting to local clients."
                        )

                        # 3. --- This is the logic moved from broadcast_game_state ---
                        # Get all local websockets for this specific game
                        local_sockets = list(
                            self._local_connections.get(game_id, set())
                        )

                        # Loop through them and send the exact message we just received
                        for ws in local_sockets:
                            try:
                                await ws.send(message_json)
                            except Exception:
                                logger.error(
                                    f"Error sending to a websocket for game '{game_id}'. Disconnecting.",
                                    exc_info=False,
                                )
                                # Don't block other broadcasts, schedule the disconnect to run separately
                                asyncio.create_task(self.disconnect(game_id, ws))

                        logger.info(
                            f"Broadcasted event to {len(local_sockets)} local clients for game '{game_id}'."
                        )

                except Exception:
                    logger.error(
                        "Error in Redis listener. Re-subscribing in 5s...",
                        exc_info=True,
                    )
                    await asyncio.sleep(5)
                    # Re-subscribe logic (your existing code for this is good)
                    if self._subscribed_games:
                        channels = [f"game:{gid}" for gid in self._subscribed_games]
                        await self.pubsub.subscribe(*channels)  # type: ignore

            else:
                await asyncio.sleep(3)

    async def connect(self, game_id: str, websocket: Websocket):
        """Registers a new websocket and subscribes to the game's Redis channel if not already."""
        logger.info(f"Connecting WebSocket to game '{game_id}'.")
        self._local_connections[game_id].add(websocket)

        if game_id not in self._subscribed_games:
            logger.debug(
                f"First local connection for '{game_id}'. Subscribing to Redis channel."
            )
            await self.pubsub.subscribe(f"game:{game_id}")  # type: ignore
            self._subscribed_games.add(game_id)

    async def disconnect(self, game_id: str, websocket: Websocket):
        """Removes a websocket and unsubscribes from the Redis channel if it's the last one."""
        logger.info(f"Disconnecting WebSocket from game '{game_id}'.")
        self._local_connections[game_id].discard(websocket)

        if not self._local_connections[game_id]:
            del self._local_connections[game_id]
            if game_id in self._subscribed_games:
                logger.debug(
                    f"Last local connection for '{game_id}' gone. Unsubscribing."
                )
                await self.pubsub.unsubscribe(f"game:{game_id}")  # type: ignore
                self._subscribed_games.discard(game_id)

    async def publish_event(self, game_id: str, payload: Dict[str, Any]):
        """
        Publishes a full event payload as a JSON string to the game's Redis channel.
        """
        channel = f"game:{game_id}"
        message_json = json.dumps(payload)

        await self.redis_client.publish(channel, message_json)  # type: ignore
        logger.info(f"Published '{payload.get('type')}' event to channel '{channel}'.")

    async def notify_game_update(self, game_id: str):
        """
        Publishes a notification to the game's Redis channel.
        This will be called by HTTP routes after a state change.
        """
        channel = f"game:{game_id}"
        logger.info(f"Publishing update notification to Redis channel '{channel}'.")

        await self.redis_client.publish(channel, json.dumps({"status": "updated"}))  # type: ignore

    async def broadcast_game_state(self, game_id: str):
        """
        Fetches the serialized game state using the repository and broadcasts it
        to LOCAL clients for that game. Used for initial state sync.
        """
        logger.debug(
            f"--- Broadcasting state for game '{game_id}' to local clients ---"
        )

        async with AsyncSessionLocal() as db_session:
            game_repo = GameRepository(db_session)
            auth_repo = AuthRepository(db_session)

            payload = await game_repo.get_serialized_game_state(game_id, auth_repo)

            if not payload:
                logger.warning(
                    f"Broadcast failed: Game '{game_id}' not found during payload creation."
                )
                return

            message_json = json.dumps(payload)

        # The rest of the function is just the sending loop, which is unchanged.
        local_sockets = list(self._local_connections.get(game_id, set()))
        for ws in local_sockets:
            try:
                await ws.send(message_json)
            except Exception:
                logger.error(
                    f"Error sending to a websocket for game '{game_id}'. Disconnecting.",
                    exc_info=False,
                )
                asyncio.create_task(self.disconnect(game_id, ws))

        logger.info(
            f"Broadcasted initial state to {len(local_sockets)} local clients for game '{game_id}'."
        )
