import os
from dotenv import load_dotenv

APP_ENV = os.getenv("APP_ENV")

if APP_ENV in ("local", "cloud"):
    load_dotenv(f".env.{APP_ENV}")


def get_required_env(var_name: str) -> str:
    """
    Gets a required environment variable, raising a clear error if it is not set.
    This guarantees the return type is 'str', not 'str | None'.
    """
    value = os.getenv(var_name)
    if value is None:
        raise ValueError(
            f"Error: Required environment variable '{var_name}' is not set. Please check your .env file."
        )
    return value


DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")

SECRET_KEY = get_required_env("SECRET_KEY")

DB_USER = get_required_env("DB_USER")
DB_PASSWORD = get_required_env("DB_PASSWORD")
DB_HOST = get_required_env("DB_HOST")
DB_PORT = get_required_env("DB_PORT")
DB_NAME = get_required_env("DB_NAME")

DATABASE_URL = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

RATELIMIT_STORAGE_URI = get_required_env("RATELIMIT_STORAGE_URI")
