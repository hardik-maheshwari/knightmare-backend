from abc import ABC, abstractmethod
from typing import AsyncIterator, TypedDict


class PubSubMessage(TypedDict):
    channel: str
    data: str


# 2. The Interface
class PubSubProvider(ABC):

    # Notice: No __init__ defined here.

    @abstractmethod
    async def subscribe(self, channel: str) -> None:
        """Registers interest in a channel."""
        pass

    @abstractmethod
    async def unsubscribe(self, channel: str) -> None:
        """Unregisters interest in a channel."""
        pass

    @abstractmethod
    async def publish(self, channel: str, message: str) -> None:
        """Sends a message to all subscribers of the channel."""
        pass

    @abstractmethod
    def listen(self) -> AsyncIterator[PubSubMessage]:
        """
        Continuously yields messages.
        MUST return the standardized 'PubSubMessage' dict,
        stripping away any Redis/RabbitMQ specific metadata.
        """
        pass
