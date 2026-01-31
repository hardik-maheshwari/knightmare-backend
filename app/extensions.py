import config
from typing import Dict, Optional, Any
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from quart_rate_limiter import RateLimiter

# 1. Database Setup
async_engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,
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
    A simple in-memory dictionary that mimics the Redis async methods.
    Type hints match Redis with decode_responses=True (str).
    """
    def __init__(self) -> None:
        # Explicitly define the dictionary type
        self.store: Dict[str, str] = {}
        print("--- USING MOCK REDIS (In-Memory) ---")

    async def get(self, key: str) -> Optional[str]:
        return self.store.get(key)

    async def setex(self, key: str, time: int, value: str) -> bool:
        # We ignore 'time' (expiration) for the simple in-memory version
        self.store[key] = value
        return True

    async def delete(self, key: str) -> int:
        if key in self.store:
            del self.store[key]
            return 1
        return 0


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

    redis_url = getattr(config, "REDIS_URL", config.RATELIMIT_STORAGE_URI)
    
    url_options = parse_url(redis_url)
   
    app_caching_pool = ConnectionPool(**url_options, decode_responses=True)

    redis_client = redis.Redis(connection_pool=app_caching_pool)

else:
    
    rate_limiter = RateLimiter()

    # General Redis Client: Use Mock
    redis_client = MockRedis()