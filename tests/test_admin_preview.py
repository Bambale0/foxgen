import pytest

from foxgen.admin.policy import ALL_SCOPES, AdminContext
from foxgen.admin.preview_service import AdminPreviewService


class FakeExecutor:
    def __init__(self) -> None:
        self.audit_calls: list[dict[str, object]] = []

    async def audit_read(self, **kwargs: object) -> None:
        self.audit_calls.append(kwargs)


@pytest.mark.asyncio
async def test_generation_preview_validates_without_submit_or_charge() -> None:
    executor = FakeExecutor()
    service = AdminPreviewService(executor)  # type: ignore[arg-type]
    context = AdminContext(
        user_id=1,
        role="superadmin",
        scopes=ALL_SCOPES,
        request_id="preview-1",
    )

    result = await service.generation_preview(
        context=context,
        model_slug="seedream-5-pro",
        input_payload={
            "prompt": "A commercial studio photograph of a red fox",
            "aspect_ratio": "1:1",
            "quality": "basic",
            "output_format": "png",
        },
    )

    assert result["model_slug"] == "seedream-5-pro"
    assert result["would_submit"] is False
    assert result["would_reserve_balance"] is False
    assert executor.audit_calls
