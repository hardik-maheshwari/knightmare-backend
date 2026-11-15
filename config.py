import os
from typing import Any, Dict, List, Union

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

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


def _env_bool(var_name: str, default: str = "false") -> bool:
    return os.getenv(var_name, default).lower() in ("true", "1", "t", "yes")


DEBUG = _env_bool("DEBUG")
USE_REDIS = _env_bool("USE_REDIS")
# Testing aid: POST /api/games/<id>/undo/ takes back a move without the
# opponent's consent. Off by default (the route returns 404).
ENABLE_GOD_MODE_UNDO = _env_bool("ENABLE_GOD_MODE_UNDO")

SECRET_KEY = get_required_env("SECRET_KEY")


# --- Database ---
_raw_url = os.getenv("INTERNAL_DATABASE_URL") or os.getenv("DATABASE_URL")

if not _raw_url:
    # If not found, build it from parts
    DB_USER = get_required_env("DB_USER")
    DB_PASSWORD = get_required_env("DB_PASSWORD")
    DB_HOST = get_required_env("DB_HOST")
    DB_PORT = get_required_env("DB_PORT")
    DB_NAME = get_required_env("DB_NAME")

    _raw_url = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Hosted providers (Neon, Render, Supabase, Railway) hand out libpq-style URLs:
# 'postgres://' or 'postgresql://' with '?sslmode=require'. SQLAlchemy would pick
# psycopg2 for those (not installed), and asyncpg rejects libpq-only query params,
# so normalise the driver and translate sslmode into asyncpg's 'ssl' connect arg.
_url = make_url(_raw_url)
if _url.drivername in ("postgres", "postgresql", "postgresql+psycopg2"):
    _url = _url.set(drivername="postgresql+asyncpg")

_query = dict(_url.query)
_sslmode = _query.pop("sslmode", None)
_query.pop("channel_binding", None)  # libpq-only, asyncpg doesn't support it
_url = _url.set(query=_query)

DATABASE_URL: str = _url.render_as_string(hide_password=False)
# Same URL with the password masked, safe to log.
DATABASE_URL_SAFE: str = _url.render_as_string(hide_password=True)

DATABASE_CONNECT_ARGS: Dict[str, Any] = {}
if _sslmode in ("require", "verify-ca", "verify-full"):
    DATABASE_CONNECT_ARGS["ssl"] = "require" if _sslmode == "require" else True


# --- Redis / rate limiting ---
RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
REDIS_URL = os.getenv("REDIS_URL") or RATELIMIT_STORAGE_URI


# --- CORS ---
# Comma-separated list of allowed origins, e.g. "https://knightmare.vercel.app".
# Defaults to "*" (fine here: auth is a Bearer header, not cookies).
_cors_origins: List[str] = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
    if origin.strip()
]
CORS_ALLOW_ORIGIN: Union[str, List[str]] = (
    "*" if not _cors_origins or "*" in _cors_origins else _cors_origins
)
