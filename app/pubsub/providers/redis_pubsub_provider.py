from typing import AsyncIterator
from redis.asyncio.client import Redis, PubSub
from app.pubsub.base import PubSubProvider, PubSubMessage
from app.logger_setup import get_logger

logger = get_logger(__name__)


class RedisPubSubProvider(PubSubProvider):
    """
    Implementation of PubSubProvider using Redis.
    """

    def __init__(self, redis_client: Redis):
        # We inject the client (Dependency Injection)
        self.redis = redis_client
        self.pubsub: PubSub = self.redis.pubsub() # type: ignore

    async def subscribe(self, channel: str) -> None:
        await self.pubsub.subscribe(channel)  # type: ignore
        logger.debug(f"[RedisProvider] Subscribed to '{channel}'")

    async def unsubscribe(self, channel: str) -> None:
        await self.pubsub.unsubscribe(channel)  # type: ignore
        logger.debug(f"[RedisProvider] Unsubscribed from '{channel}'")

    async def publish(self, channel: str, message: str) -> None:
        await self.redis.publish(channel, message)  # type: ignore
        logger.debug(f"[RedisProvider] Published to '{channel}'")

    async def listen(self) -> AsyncIterator[PubSubMessage]:
        """
        Yields messages from Redis, converting them to the standard format.
        Ignores 'subscribe'/'unsubscribe' confirmation events.
        """
        # The redis library's listen() yields a dictionary.
        # We iterate over it.
        async for raw_message in self.pubsub.listen():  # type: ignore
            assert isinstance(raw_message,dict)

            # We only care about actual data messages
            if raw_message and raw_message.get("type") == "message":   # type: ignore

                # --- THE ADAPTER LOGIC ---
                # Convert Redis format to our Standard format
                standard_msg: PubSubMessage = {
                    "channel": raw_message["channel"],
                    "data": raw_message["data"],
                }

                yield standard_msg