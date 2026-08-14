from __future__ import annotations

from uuid import UUID

import pytest

from foxgen.bot.generation_capabilities import VideoGenerationType
from foxgen.bot.generation_draft import default_image_flow_data, default_video_flow_data
from foxgen.bot.reference_memory import _apply_selected, _saved_image_capacity
from foxgen.core.errors import SubmissionError


REF_A = str(UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
REF_B = str(UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"))


def test_image_memory_selection_appends_after_temporary_inputs() -> None:
    data = default_image_flow_data(42)
    data["media"] = [{"kind": "image", "storage_key": "inputs/42/local.png"}]

    result = _apply_selected(data, [REF_A, REF_B])

    assert result == [
        {"kind": "image", "storage_key": "inputs/42/local.png"},
        {"kind": "image", "reference_id": REF_A},
        {"kind": "image", "reference_id": REF_B},
    ]


def test_first_last_memory_selection_preserves_selection_order() -> None:
    data = default_video_flow_data(42)
    data["video_type"] = VideoGenerationType.FIRST_LAST.value
    assert _saved_image_capacity(data) == 2

    result = _apply_selected(data, [REF_B, REF_A])

    assert result == [
        {"kind": "image", "reference_id": REF_B},
        {"kind": "image", "reference_id": REF_A},
    ]


def test_first_frame_rejects_more_saved_images_than_model_allows() -> None:
    data = default_video_flow_data(42)
    data["video_type"] = VideoGenerationType.FIRST_FRAME.value

    with pytest.raises(SubmissionError):
        _apply_selected(data, [REF_A, REF_B])
