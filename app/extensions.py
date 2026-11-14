import time
import config
from typing import Dict, Optional, Any, Tuple
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from quart_rate_limiter import RateLimiter

# 1. Database Setup
async_engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,
    connect_args=config.DATABASE_CONNECT_ARGS,
    # Hosted/serverless Postgres (Neon etc.) drops idle connections; check before use.
    pool_pre_ping=True,
    pool_recycle=300,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


# 2. Mock Redis Class (Strictly Typed)
class MockRedis:
    """
    A simple in-memory dictionary that mimics the Redis async methods we use.
    Type hints match Redis with decode_responses=True (str).

    Only valid for a SINGLE server process (one instance, one worker): the data
    lives in this process's memory.
    """
    def __init__(self) -> None:
        # key -> (value, expires_at monotonic timestamp)
        self.store: Dict[str, Tuple[str, float]] = {}
        print("--- USING MOCK REDIS (In-Memory) ---")

    def _purge_expired(self) -> None:
        now = time.monotonic()
        for key in [k for k, (_, exp) in self.store.items() if exp <= now]:
            del self.store[key]

    async def get(self, key: str) -> Optional[str]:
        self._purge_expired()
        entry = self.store.get(key)
        return entry[0] if entry else None

    async def setex(self, key: str, time_seconds: int, value: Any) -> bool:
        self._purge_expired()
        self.store[key] = (str(value), time.monotonic() + time_seconds)
        return True

    async def getdel(self, key: str) -> Optional[str]:
        self._purge_expired()
        entry = self.store.pop(key, None)
        return entry[0] if entry else None

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


# 3. Conditional Setup
# We use Union/Any for the client type to prevent static analysis errors 
# when switching between the real Redis class and our Mock class.
redis_client: Any = None

if config.USE_REDIS:
    # --- PROD MODE (With Redis) ---
    import redis.asyncio as redis
    from quart_rate_limiter.redis_store import RedisStore
    from redis.asyncio.connection import ConnectionPool, parse_url
    # from redis.asyncio.client import Redis

    redis_store = RedisStore(address=config.RATELIMIT_STORAGE_URI)
    rate_limiter = RateLimiter(store=redis_store)

    url_options = parse_url(config.REDIS_URL)
   
    app_caching_pool = ConnectionPool(**url_options, decode_responses=True)

    redis_client = redis.Redis(connection_pool=app_caching_pool)

else:
    
    rate_limiter = RateLimiter()

    # General Redis Client: Use Mock
    redis_client = MockRedis()