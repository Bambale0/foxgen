import time

from redis.asyncio import Redis

from foxgen.core.errors import ErrorCode, SubmissionError


class RedisSubmissionRateLimiter:
    def __init__(
        self,
        redis: Redis[str],
        *,
        user_limit_per_minute: int,
        global_limit_per_minute: int,
    ) -> None:
        self._redis = redis
        self._user_limit = user_limit_per_minute
        self._global_limit = global_limit_per_minute

    async def check(self, user_id: int) -> None:
        bucket = int(time.time() // 60)
        user_key = f"foxgen:rate:submission:user:{user_id}:{bucket}"
        global_key = f"foxgen:rate:submission:global:{bucket}"

        pipeline = self._redis.pipeline(transaction=True)
        pipeline.incr(user_key)
        pipeline.expire(user_key, 120)
        pipeline.incr(global_key)
        pipeline.expire(global_key, 120)
        results = await pipeline.execute()

        user_count = int(results[0])
        global_count = int(results[2])
        if user_count > self._user_limit:
            raise SubmissionError(
                ErrorCode.RATE_LIMITED,
                "Слишком много запусков за минуту. Подождите и повторите.",
                retryable=True,
                details={"scope": "user", "limit": self._user_limit},
            )
        if global_count > self._global_limit:
            raise SubmissionError(
                ErrorCode.RATE_LIMITED,
                "Сервис временно перегружен. Повторите запуск немного позже.",
                retryable=True,
                details={"scope": "global", "limit": self._global_limit},
            )
