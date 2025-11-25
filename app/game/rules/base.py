from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
from .context import MoveContext


class GameRuleHandler(ABC):
    def __init__(self):
        self._next: Optional[GameRuleHandler] = None

    def set_next(self, handler: GameRuleHandler) -> GameRuleHandler:
        self._next = handler
        return handler

    @abstractmethod
    def check(self, move_context: MoveContext) -> None:
        """
        Validates the rule.
        If invalid, RAISES a Domain Exception (GameError).
        If valid, calls the next handler.
        """
        if self._next:
            self._next.check(move_context)
