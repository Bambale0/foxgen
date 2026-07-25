from typing import Any, cast

from aiogram.fsm.storage.redis import RedisStorage

from foxgen.bot.app import FSM_EVENT_LOCK_TIMEOUT_SECONDS, create_event_isolation


class StubStorage:
    def __init__(self) -> None:
        self.lock_kwargs: dict[str, Any] | None = None
        self.isolation = object()

    def create_isolation(self, **kwargs: Any) -> object:
        self.lock_kwargs = kwargs.get("lock_kwargs")
        return self.isolation


def test_dispatcher_uses_bounded_redis_event_isolation() -> None:
    storage = StubStorage()

    isolation = create_event_isolation(cast(RedisStorage, storage))

    assert isolation is storage.isolation
    assert storage.lock_kwargs == {"timeout": FSM_EVENT_LOCK_TIMEOUT_SECONDS}
    assert FSM_EVENT_LOCK_TIMEOUT_SECONDS >= 120
