import httpx
import pytest

from foxgen.core.errors import ErrorCode, ProviderError
from foxgen.providers.kie.client import KieClient


@pytest.mark.asyncio
async def test_create_task_uses_unified_market_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/jobs/createTask"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={"code": 200, "msg": "success", "data": {"taskId": "t1"}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kie.ai", transport=transport) as http:
        client = KieClient(api_key="test-key", client=http)
        task = await client.create_task(
            model="gpt-image-2-text-to-image",
            input_data={"prompt": "fox"},
        )

    assert task.task_id == "t1"


@pytest.mark.asyncio
async def test_create_task_timeout_is_not_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("response lost", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kie.ai", transport=transport) as http:
        client = KieClient(api_key="test-key", client=http)
        with pytest.raises(ProviderError) as error:
            await client.create_task(model="x", input_data={"prompt": "fox"})

    assert error.value.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert error.value.retryable is True
    assert calls == 1


@pytest.mark.asyncio
async def test_maps_insufficient_credits() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(402, json={"code": 402, "msg": "insufficient credits"})
    )
    async with httpx.AsyncClient(base_url="https://api.kie.ai", transport=transport) as http:
        client = KieClient(api_key="test-key", client=http)
        with pytest.raises(ProviderError) as error:
            await client.create_task(model="x", input_data={})

    assert error.value.code == ErrorCode.INSUFFICIENT_CREDITS
    assert error.value.retryable is False
