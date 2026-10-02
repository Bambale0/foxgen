"""Independent examples from the partner guide, checked 2026-10-02."""
import json
from pathlib import Path

import pytest


def test_registry_matches_live_snapshot_without_treating_examples_as_available():
    from happyfox_neironych import MODELS
    snapshot = json.loads(Path('docs/providers/neironych-models-20261002.json').read_text())
    assert set(MODELS) == {row['id'] for row in snapshot['data']}
    assert MODELS['gpt-5.6-luna'].endpoint == '/v1/responses'
    assert MODELS['glm-5.3-flash'].endpoint == '/v1/chat/completions'


def test_seedance_first_last_uses_exact_documented_body():
    from happyfox_neironych import video_request
    request = video_request('seedance-2.5', 'Move between frames', key='operation-123', duration=4,
        ratio='adaptive', start_image='https://media.example/start.jpg', end_image='https://media.example/end.jpg')
    assert request.payload == {
        'model': 'seedance-2.5', 'prompt': 'Move between frames', 'duration': 4,
        'resolution': '720p', 'aspect_ratio': 'adaptive', 'n': 1,
        'start_image': {'url': 'https://media.example/start.jpg'},
        'end_image': {'url': 'https://media.example/end.jpg'},
    }
    restored = type(request).from_dict(request.to_dict())
    assert restored.body == request.body
    assert restored.key == 'operation-123'


@pytest.mark.parametrize('changes', [
    {'duration': 3}, {'duration': True}, {'resolution': '4k'}, {'ratio': 'adaptive'},
    {'generate_audio': False}, {'end_image': 'https://media.example/end.png'},
    {'start_image': 'https://media.example/start.png', 'videos': ['https://media.example/ref.mp4']},
    {'images': ['https://media.example/ref.jpg'] * 31},
])
def test_seedance25_invalid_combinations_fail_without_a_provider_call(changes):
    from happyfox_neironych import ContractError, video_request
    args = {'duration': 4, 'ratio': '9:16', **changes}
    with pytest.raises(ContractError):
        video_request('seedance-2.5', 'scene', key='operation-123', **args)


def test_all_three_image_models_and_three_text_models_have_executable_requests():
    from happyfox_neironych import image_request, text_request
    for model in ('nano-banana-2', 'nano-banana-pro', 'gpt-image-2.5-sunburst'):
        request = image_request(model, 'Preserve the label "A&B"\nnext line', key='image-operation-123', images=['https://media.example/ref.jpg'])
        assert request.endpoint == '/v1/images/edits'
        assert request.payload['images'] == [{'image_url': 'https://media.example/ref.jpg'}]
        assert request.payload['response_format'] == 'b64_json'
        assert request.payload['prompt'] == 'Preserve the label "A&B"\nnext line'
    for model in ('glm-5.3-flash', 'gpt-5.6-luna', 'grok-4.5'):
        request = text_request(model, 'Explain', key='text-operation-123', instructions='Be clear')
        assert request.model.id == model
        assert 'reasoning' not in request.payload
        assert 'service_tier' not in request.payload
    assert image_request('gpt-image-2.5-sunburst', 'wide', key='image-key-123', ratio='16:9', resolution='4k').payload['size'] == '3840x2160'


@pytest.mark.parametrize('changes', [{'n': 5}, {'n': True}, {'images': ['https://media.example/a.png'] * 4}, {'ratio': '21:9'}, {'resolution': '8k'}])
def test_banana2_rejects_invalid_inputs(changes):
    from happyfox_neironych import ContractError, image_request
    with pytest.raises(ContractError):
        image_request('nano-banana-2', 'photo', key='image-operation-123', **changes)


def test_seedance25_edit_and_audio_only_are_supported():
    from happyfox_neironych import video_request
    edit = video_request('seedance-2.5', 'Replace sky in @Video 1', key='edit-operation-123', duration=-1, ratio='adaptive', mode='edit', videos=['https://media.example/v.mp4'])
    assert edit.payload['duration'] == -1
    assert edit.payload['omni_reference_task_type'] == 'edit'
    audio = video_request('seedance-2.5', 'Animate @Audio 1', key='audio-operation-123', duration=4, audios=['https://media.example/a.mp3'])
    assert audio.payload['reference_audios'] == [{'url': 'https://media.example/a.mp3'}]


@pytest.mark.parametrize('changes', [
    {'videos': ['https://media.example/v.mp4']}, {'audios': ['https://media.example/a.mp3']},
    {'start_image': 'https://media.example/a.png', 'images': ['https://media.example/b.png']},
    {'images': ['https://media.example/a.png'], 'resolution': '1080p'},
    {'duration': 16}, {'end_image': 'https://media.example/b.png'},
])
def test_grok_rejects_seedance_fields_and_invalid_reference_modes(changes):
    from happyfox_neironych import ContractError, video_request
    with pytest.raises(ContractError):
        video_request('grok-imagine-video-1.5', 'video', key='video-operation-123', **{'duration': 4, **changes})


@pytest.mark.parametrize('url', ['http://media.example/a.png', 'https://127.0.0.1/a.png', 'https://user:password@media.example/a.png'])
def test_credentials_and_private_media_origins_are_rejected(url):
    from happyfox_neironych import ContractError, video_request
    with pytest.raises(ContractError):
        video_request('seedance-2.0', 'video', key='video-operation-123', duration=4, images=[url])
