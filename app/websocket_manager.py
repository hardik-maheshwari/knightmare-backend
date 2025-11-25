import asyncio
import json
from collections import defaultdict
from typing import Any, Optional, Set, Dict, TypedDict, AsyncIterator, cast
from quart.wrappers import Websocket
from redis.asyncio.client import PubSub
from app.extensions import redis_client
from app.logger_setup import get_logger

logger = get_logger(__name__)


class RedisPubSubMessage(TypedDict):
    """
    Defines the structure of a message received from Redis Pub/Sub
    when 'decode_responses=True' is used on the connection pool.
    """

    type: str
    channel: str
    pattern: Optional[str]
    data: str


class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts for chess games using Redis Pub/Sub
    for multi-process scalability.
    """

    def __init__(self):

        self._local_connections: Dict[str, Set[Websocket]] = defaultdict(set)

        self.redis_client = redis_client
        self.pubsub: PubSub = self.redis_client.pubsub() # type: ignore
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
            try:

                if self._subscribed_games:
                    listener: AsyncIterator[RedisPubSubMessage] = cast(
                        AsyncIterator[RedisPubSubMessage], self.pubsub.listen() # type: ignore
                    )
                    async for message in listener:
                        # Check if the message is a real event (not a subscribe/unsubscribe confirmation)
                        if message and message.get("type") == "message":
                            channel_str = message["channel"]
                            game_id = channel_str.split(":", 1)[1]
                            message_json = message["data"]

                            logger.debug(
                                f"Received pub/sub event for game '{game_id}'."
                            )

                            # Get all local websockets for this specific game
                            local_sockets = list(
                                self._local_connections.get(game_id, set())
                            )

                            # Create a list of tasks to send to all sockets concurrently
                            broadcast_tasks = [
                                ws.send(message_json) for ws in local_sockets
                            ]
                            results = await asyncio.gather(
                                *broadcast_tasks, return_exceptions=True
                            )

                            # Handle any failed sends (e.g., closed connections)
                            for i, result in enumerate(results):
                                if isinstance(result, Exception):
                                    ws_to_disconnect = local_sockets[i]
                                    logger.error(
                                        f"Error sending to websocket for game '{game_id}'. Scheduling disconnect."
                                    )
                                    # Don't block, schedule the disconnect to run in the background
                                    asyncio.create_task(
                                        self.disconnect(game_id, ws_to_disconnect)
                                    )

                            logger.info(
                                f"Broadcasted event to {len(local_sockets)} clients for game '{game_id}'."
                            )

                else:
                    await asyncio.sleep(5)

            except Exception:
                logger.error(
                    "Error in Redis listener. Re-subscribing in 5s...", exc_info=True
                )
                await asyncio.sleep(5)
                # Re-subscribe to all necessary channels upon reconnection
                if self._subscribed_games:
                    channels = [f"game:{gid}" for gid in self._subscribed_games]
                    await self.pubsub.subscribe(*channels) # type: ignore

    async def connect(self, game_id: str, websocket: Websocket):
        """Registers a new websocket and subscribes to the game's Redis channel if not already."""
        logger.info(f"Connecting WebSocket to game '{game_id}'.")
        self._local_connections[game_id].add(websocket)

        if game_id not in self._subscribed_games:
            logger.debug(
                f"First local connection for '{game_id}'. Subscribing to Redis channel."
            )
            await self.pubsub.subscribe(f"game:{game_id}") # type: ignore
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
                await self.pubsub.unsubscribe(f"game:{game_id}") # type: ignore
                self._subscribed_games.discard(game_id)

    async def publish_event(self, game_id: str, payload: Dict[str, Any]):
        """
        Publishes a full event payload as a JSON string to the game's Redis channel.
        """
        channel = f"game:{game_id}"
        message_json = json.dumps(payload)

        await self.redis_client.publish(channel, message_json) # type: ignore
        logger.info(f"Published '{payload.get('type')}' event to channel '{channel}'.")

    async def notify_game_update(self, game_id: str):
        """
        Publishes a notification to the game's Redis channel.
        This will be called by HTTP routes after a state change.
        """
        channel = f"game:{game_id}"
        logger.info(f"Publishing update notification to Redis channel '{channel}'.")

        await self.redis_client.publish(channel, json.dumps({"status": "updated"}))  # type: ignore
