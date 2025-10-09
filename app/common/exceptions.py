class ValidationError(Exception):
    """Raised when user input fails validation checks."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class CacheMissError(Exception):
    """Internal exception to signal that a required item was not in the cache."""
    pass