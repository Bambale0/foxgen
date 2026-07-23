import httpx
import pytest
import respx

from foxgen.bot.api_client import FoxGenApiClient, FoxGenApiError


@pytest.mark.asyncio
@respx.mock
async def test_bot_client_reads_prices_and_authenticated_balance() -> None:
    prices_route = respx.get("http://foxgen.test/v1/prices").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "model_slug": "seedream-5-pro",
                    "amount_units": 250,
                    "currency": "CREDIT",
                    "version": 3,
                }
            ],
        )
    )
    balance_route = respx.get("http://foxgen.test/v1/users/42/balance").mock(
        return_value=httpx.Response(
            200,
            json={
                "available_units": 1000,
                "reserved_units": 250,
                "currency": "CREDIT",
            },
        )
    )
    client = FoxGenApiClient(
        base_url="http://foxgen.test",
        internal_token="internal-secret",
    )

    try:
        prices = await client.prices()
        balance = await client.balance(42)
    finally:
        await client.aclose()

    assert prices["seedream-5-pro"].amount_units == 250
    assert balance.available_units == 1000
    assert prices_route.calls[0].request.headers.get("Authorization") is None
    assert balance_route.calls[0].request.headers["Authorization"] == "Bearer internal-secret"


@pytest.mark.asyncio
@respx.mock
async def test_bot_submission_preserves_identity_and_idempotency() -> None:
    route = respx.post("http://foxgen.test/v1/models/seedream-5-pro/tasks").mock(
        return_value=httpx.Response(
            202,
            json={
                "generation_id": "11111111-1111-1111-1111-111111111111",
                "status": "queued",
                "replayed": False,
            },
        )
    )
    client = FoxGenApiClient(
        base_url="http://foxgen.test",
        internal_token="internal-secret",
    )

    try:
        generation = await client.submit(
            user_id=42,
            username="fox-user",
            model_slug="seedream-5-pro",
            input_data={"prompt": "A fox", "aspect_ratio": "1:1"},
            idempotency_key="generation:42:request-0001",
        )
    finally:
        await client.aclose()

    request = route.calls[0].request
    assert generation.status == "queued"
    assert request.headers["Authorization"] == "Bearer internal-secret"
    assert request.headers["X-FoxGen-User-Id"] == "42"
    assert request.headers["X-FoxGen-Username"] == "fox-user"
    assert request.headers["Idempotency-Key"] == "generation:42:request-0001"


@pytest.mark.asyncio
@respx.mock
async def test_bot_client_surfaces_stable_api_errors() -> None:
    respx.post("http://foxgen.test/v1/models/seedream-5-pro/tasks").mock(
        return_value=httpx.Response(
            402,
            json={
                "error": "insufficient_credits",
                "message": "Недостаточно средств для запуска этой генерации.",
                "retryable": False,
            },
        )
    )
    client = FoxGenApiClient(
        base_url="http://foxgen.test",
        internal_token="internal-secret",
    )

    try:
        with pytest.raises(FoxGenApiError) as error:
            await client.submit(
                user_id=42,
                username=None,
                model_slug="seedream-5-pro",
                input_data={"prompt": "A fox"},
                idempotency_key="generation:42:request-0001",
            )
    finally:
        await client.aclose()

    assert error.value.status_code == 402
    assert "Недостаточно средств" in error.value.message
    assert error.value.retryable is False
