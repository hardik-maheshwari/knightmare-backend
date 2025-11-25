import asyncio
from typing import AsyncIterator, Set
from app.pubsub.base import PubSubMessage, PubSubProvider
from app.logger_setup import get_logger

logger = get_logger(__name__)

class InMemoryPubSubProvider(PubSubProvider):
    """
    A concrete implementation that runs entirely in RAM.
    Great for testing or single-process deployments.
    """

    def __init__(self):
        self.queue: asyncio.Queue[PubSubMessage] = asyncio.Queue()
        self.subscribed_channels: Set[str] = set()

    async def subscribe(self, channel: str) -> None:
        self.subscribed_channels.add(channel)
        logger.debug(f"[MemoryProvider] Subscribed to '{channel}'")

    async def unsubscribe(self, channel: str) -> None:
        self.subscribed_channels.discard(channel)
        logger.debug(f"[MemoryProvider] Unsubscribed from '{channel}'")

    async def publish(self, channel: str, message: str) -> None:
        """
        Simulates a broadcast.
        If we are subscribed to this channel locally, put it in the queue.
        """
        # In a real broker (Redis), you publish regardless of who is listening.
        # But to receive it in our listen() loop, we check our local subscription list.
        if channel in self.subscribed_channels:
            msg: PubSubMessage = {"channel": channel, "data": message}
            await self.queue.put(msg)
            logger.debug(f"[MemoryProvider] Internal Queue: {channel}")

    async def listen(self) -> AsyncIterator[PubSubMessage]:
        """
        Yields messages from the internal asyncio Queue.
        """
        while True:
            # This blocks efficiently until an item is available. No sleep needed.
            msg = await self.queue.get()
            yield msg
