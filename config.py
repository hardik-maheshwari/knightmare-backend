import os
from dotenv import load_dotenv

load_dotenv()


def get_env_safe(var_name: str, default: str = "") -> str:
    """Gets an env var, returns default if not found (instead of crashing)."""
    return os.getenv(var_name, default)


def get_required_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if value is None:
        raise ValueError(
            f"Error: Required environment variable '{var_name}' is not set."
        )
    return value


DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
USE_REDIS = os.getenv("USE_REDIS", "false").lower() == "true"

SECRET_KEY = get_required_env("SECRET_KEY")


_url = os.getenv("INTERNAL_DATABASE_URL") or os.getenv("DATABASE_URL")

if not _url:
    # If not found, build it from parts
    DB_USER = get_required_env("DB_USER")
    DB_PASSWORD = get_required_env("DB_PASSWORD")
    DB_HOST = get_required_env("DB_HOST")
    DB_PORT = get_required_env("DB_PORT")
    DB_NAME = get_required_env("DB_NAME")

    _url = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

if _url.startswith("postgres://"):
    _url = _url.replace("postgres://", "postgresql+asyncpg://", 1)

DATABASE_URL: str = _url

RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
