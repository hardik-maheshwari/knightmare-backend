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
