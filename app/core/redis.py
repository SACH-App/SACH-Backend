import redis.asyncio as redis
from app.core.config import settings

class RedisManager:
    def __init__(self):
        self.redis_client = None

    async def connect(self):
        """Initialize connection to Upstash Redis."""
        if not self.redis_client:
            self.redis_client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True
            )

    async def close(self):
        """Close connection to Upstash Redis."""
        if self.redis_client:
            await self.redis_client.aclose()

redis_manager = RedisManager()

def get_redis() -> redis.Redis:
    """Dependency to provide a Redis connection."""
    return redis_manager.redis_client
