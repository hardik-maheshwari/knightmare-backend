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


DATABASE_URL = os.getenv("INTERNAL_DATABASE_URL") or os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DB_USER = get_required_env("DB_USER")
    DB_PASSWORD = get_required_env("DB_PASSWORD")
    DB_HOST = get_required_env("DB_HOST")
    DB_PORT = get_required_env("DB_PORT")
    DB_NAME = get_required_env("DB_NAME")
    DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"  # type: ignore


if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)  # type: ignore


RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
