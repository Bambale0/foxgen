from redis.asyncio import Redis


class RedisPool:
    def __init__(self, url: str) -> None:
        self.client: Redis[str] = Redis.from_url(url, decode_responses=True)

    async def ping(self) -> None:
        await self.client.ping()

    async def close(self) -> None:
        await self.client.aclose()
