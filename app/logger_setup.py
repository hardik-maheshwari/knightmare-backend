import logging
from typing import Any, Dict
import coloredlogs  # type: ignore
import threading
import config

# --- Configuration ---
# Set this to True for development to see DEBUG logs, False for production (INFO and above)
APP_DEBUG_MODE = config.DEBUG


# --- Singleton Metaclass ---
class SingletonMeta(type):
    _instances: Dict[type, object] = {}
    _lock: threading.Lock = threading.Lock()

    def __call__(cls, *args: Any, **kwargs: Any) -> object:
        if cls not in cls._instances:  # type: ignore
            with cls._lock:
                if cls not in cls._instances:  # type: ignore
                    instance = super().__call__(*args, **kwargs)
                    cls._instances[cls] = instance
        return cls._instances[cls]


# --- LoggerConfig Class ---
class LoggerConfig(metaclass=SingletonMeta):
    def __init__(self, debug_mode: bool = False):
        # This __init__ is called only once.
        self._setup_coloredlogs(debug_mode)

    def _setup_coloredlogs(self, debug_mode: bool):
        """Sets up coloredlogs for the application's root logger."""
        root_logger = logging.getLogger()  # Get the root logger

        # Set the level for the root logger. All module loggers will inherit this
        # unless they are explicitly set to a different level.
        log_level = logging.DEBUG if debug_mode else logging.INFO
        root_logger.setLevel(log_level)

        # Clear existing handlers from the root logger to prevent duplication
        # if this setup is inadvertently called multiple times or in testing scenarios.
        if root_logger.hasHandlers():
            for handler in list(root_logger.handlers):
                root_logger.removeHandler(handler)
                handler.close()

        field_styles = coloredlogs.DEFAULT_FIELD_STYLES.copy()
        field_styles["asctime"] = {"color": "green"}
        field_styles["levelname"] = {"color": "black", "bold": True}
        field_styles["filename"] = {"color": "cyan"}
        field_styles["funcName"] = {"color": "blue"}
        field_styles["lineno"] = {"color": "magenta"}
        field_styles["name"] = {"color": "yellow"}

        level_styles = coloredlogs.DEFAULT_LEVEL_STYLES.copy()
        level_styles["debug"] = {"color": "green"}
        level_styles["info"] = {"color": "cyan", "bold": True}
        level_styles["warning"] = {"color": "yellow", "bold": True}
        level_styles["error"] = {"color": "red", "bold": True}
        level_styles["critical"] = {"color": "white", "bold": True, "background": "red"}

        # Install coloredlogs onto the root logger
        coloredlogs.install(  # type: ignore
            level=log_level,
            logger=root_logger,
            fmt="%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - [%(funcName)s] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            field_styles=field_styles,
            level_styles=level_styles,
        )
        
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


LoggerConfig(debug_mode=APP_DEBUG_MODE)


def get_logger(name: str) -> logging.Logger:
    """Helper to get a logger instance."""
    return logging.getLogger(name)
