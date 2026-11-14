class GameError(Exception):
    """Base exception for all game-related errors."""

    pass


class GameNotFoundError(GameError):
    """Raised when a game with the given ID is not found."""

    pass


class GameNotJoinableError(GameError):
    """Raised when trying to join a game that is not waiting for an opponent."""

    pass


class AlreadyInGameError(GameError):
    """Raised when a player tries to join a game they are already in."""


class MoveNotPossibleError(GameError):
    pass


class UserNotPlayerError(GameError):
    """Raised when a user attempts an action on a game they are not part of."""

    pass


class TimeoutLossError(MoveNotPossibleError):
    """
    Raised when a player's flag fell before their move arrived.

    The move is rejected, but the game-over state (status + clock) MUST still be
    committed, so the error handler sets g.force_commit for this one.
    """

    pass
