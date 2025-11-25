import asyncio
from collections import defaultdict
from typing import Dict, Set
from quart.wrappers import Websocket
from app.logger_setup import get_logger
from app.pubsub.base import PubSubProvider

logger = get_logger(__name__)


class BaseWebSocketManager:
    """
    The Abstraction in the Bridge Pattern.
    It manages connection lifecycles but delegates transmission to the Provider.
    """

    def __init__(self, pubsub_provider: PubSubProvider):

        self.provider = pubsub_provider

        # Local state: channel_name -> Set[Websockets]
        self._local_connections: Dict[str, Set[Websocket]] = defaultdict(set)
        self._listening_task: asyncio.Task[None] | None = None
        self._active_subscriptions: Set[str] = set()

    async def startup(self):
        """Starts the background listener."""
        if not self._listening_task:
            self._listening_task = asyncio.create_task(self._listener_loop())
            logger.info("Manager background listener started.")

    async def connect(self, channel: str, websocket: Websocket):
        self._local_connections[channel].add(websocket)

        if channel not in self._active_subscriptions:
            await self.provider.subscribe(channel)
            self._active_subscriptions.add(channel)
            logger.info(f"Subscribed provider to '{channel}'")

        logger.info(f"Connected client to '{channel}'")

    async def disconnect(self, channel: str, websocket: Websocket):
        self._local_connections[channel].discard(websocket)

        if not self._local_connections[channel]:
            del self._local_connections[channel]

            if channel in self._active_subscriptions:
                await self.provider.unsubscribe(channel)
                self._active_subscriptions.discard(channel)
                logger.info(f"Unsubscribed provider from '{channel}'")

    async def broadcast_to_local(self, channel: str, message: str):
        sockets = self._local_connections.get(channel)
        if not sockets:
            return

        active_sockets = list(sockets)

        tasks = [ws.send(message) for ws in active_sockets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                bad_socket = active_sockets[i]
                logger.warning(f"Dead socket in '{channel}'. Cleaning up.")
                asyncio.create_task(self.disconnect(channel, bad_socket))

    async def _listener_loop(self):
        logger.info("Listener loop started.")

        while True:
            try:
                
                if self._active_subscriptions:

                    # We have active games, so we listen.
                    # This will block until a message arrives.
                    async for msg in self.provider.listen():

                        # Safety Check: If we lost all subs while listening, stop.
                        if not self._active_subscriptions:
                            break

                        channel = msg["channel"]
                        data = msg["data"]
                        await self.broadcast_to_local(channel, data)

                else:
                    # 2. THE FIX: If no subscriptions, sleep to yield control.
                    # This prevents the infinite CPU loop.
                    await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Listener error: {e}. Retrying...", exc_info=True)
                await asyncio.sleep(5)
                await self._resubscribe_all()

    async def _resubscribe_all(self):
        if not self._local_connections:
            return

        logger.info("Attempting to re-subscribe to all active channels...")

        # 1. Clear the cache because the provider state was lost/reset
        self._active_subscriptions.clear()

        for channel in list(self._local_connections.keys()):
            try:
                await self.provider.subscribe(channel)
                # 2. Mark as active again upon success
                self._active_subscriptions.add(channel)
            except Exception:
                logger.warning(f"Failed to re-subscribe to {channel}")
