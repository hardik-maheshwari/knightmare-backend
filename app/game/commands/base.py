from abc import ABC, abstractmethod
from typing import Any


class IGameCommand(ABC):
    """
    The contract for all game-changing operations (Move, Resign, OfferDraw).
    """

    @abstractmethod
    async def execute(self) -> Any:
        """
        Performs the action, updates the DB, and broadcasts events.
        """
        pass

    
