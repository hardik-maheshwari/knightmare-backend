import config
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from quart_rate_limiter import RateLimiter
from quart_rate_limiter.redis_store import RedisStore
from redis.asyncio.connection import ConnectionPool, parse_url
from redis.asyncio.client import Redis


async_engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# 3. Create a Declarative Base
# All of our model classes (User, Game, Move) will inherit from this class.
# This is how SQLAlchemy's ORM knows which classes map to which tables.
Base = declarative_base()
rate_limiter = RateLimiter()

redis_store = RedisStore(address=config.RATELIMIT_STORAGE_URI)
rate_limiter = RateLimiter(store=redis_store)

url_options = parse_url(config.RATELIMIT_STORAGE_URI)
app_caching_pool = ConnectionPool(**url_options, decode_responses=True)
redis_client: Redis = redis.Redis(connection_pool=app_caching_pool)
