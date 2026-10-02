"""Versioned partner contracts, independent of any chat framework or wallet."""
from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


class ContractError(ValueError):
    """Invalid local request; no paid provider operation has been submitted."""


@dataclass(frozen=True, slots=True)
class Model:
    id: str
    label: str
    kind: str
    endpoint: str


MODELS = {
    row[0]: Model(*row)
    for row in (
        ("glm-5.3-flash", "GLM-5.3 Flash", "text", "/v1/chat/completions"),
        ("gpt-5.6-luna", "GPT-5.6 Luna", "text", "/v1/responses"),
        ("grok-4.5", "Grok 4.5", "text", "/v1/responses"),
        ("gpt-image-2.5-sunburst", "GPT Image 2.5 Sunburst", "image", "/v1/images/generations"),
        ("nano-banana-2", "Nano Banana 2", "image", "/v1/images/generations"),
        ("nano-banana-pro", "Nano Banana Pro", "image", "/v1/images/generations"),
        ("grok-imagine-video-1.5", "Grok Imagine Video 1.5", "video", "/v1/videos/generations"),
        ("seedance-2.0", "Seedance 2.0", "video", "/v1/videos/generations"),
        ("seedance-2.5", "Seedance 2.5", "video", "/v1/videos/generations"),
    )
}
BASE_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4")


def model_spec(model: str, kind: str) -> Model:
    spec = MODELS.get(model)
    if spec is None or spec.kind != kind:
        raise ContractError("Unsupported provider model for this operation")
    return spec


def integer(value: Any, minimum: int, maximum: int, name: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def media_url(value: str, *, allow_data: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractError("Media URL must be a nonempty string without surrounding whitespace")
    if allow_data and re.match(r"^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$", value):
        return value
    try:
        parts = urlsplit(value)
        hostname = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        raise ContractError("Invalid media URL") from None
    if parts.scheme != "https" or not hostname or parts.username or parts.password or parts.fragment or port not in (None, 443):
        raise ContractError("Media must use a public HTTPS URL without embedded credentials")
    if hostname in {"localhost", "metadata.google.internal"} or hostname.endswith((".localhost", ".local", ".internal")):
        raise ContractError("Private media origins are not allowed")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ContractError("Private media addresses are not allowed")
    return value


def references(values: list[str] | None, limit: int, *, allow_data: bool = False) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)) or len(values) > limit:
        raise ContractError(f"At most {limit} references are supported")
    # Preserve order and duplicates: @Image N refers to the original sequence.
    return [media_url(value, allow_data=allow_data) for value in values]


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    endpoint: str
    key: str
    body: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not 8 <= len(self.key) <= 160 or any(ord(c) < 33 or ord(c) > 126 for c in self.key):
            raise ContractError("Idempotency-Key must be 8..160 printable ASCII characters")
        try:
            payload = json.loads(self.body)
        except (TypeError, ValueError):
            raise ContractError("Invalid persisted request body") from None
        if not isinstance(payload, dict) or payload.get("model") not in MODELS:
            raise ContractError("Invalid persisted model")
        spec = MODELS[payload["model"]]
        allowed = {spec.endpoint}
        if spec.kind == "image":
            allowed.add("/v1/images/edits")
        if self.endpoint not in allowed:
            raise ContractError("Invalid persisted request endpoint")
        if spec.kind == "video" and len(self.body.encode("utf-8")) >= 1024 * 1024:
            raise ContractError("Video JSON must be smaller than 1 MiB")

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.body)

    @property
    def model(self) -> Model:
        return MODELS[self.payload["model"]]

    def to_dict(self) -> dict[str, Any]:
        return {"version": 1, "endpoint": self.endpoint, "key": self.key, "body": self.body}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PreparedRequest:
        if value.get("version") != 1:
            raise ContractError("Unknown persisted contract version")
        return cls(value["endpoint"], value["key"], value["body"])


def prepared(endpoint: str, key: str, payload: dict[str, Any]) -> PreparedRequest:
    return PreparedRequest(endpoint, key, json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))


def video_request(
    model: str, prompt: str, *, key: str, duration: int,
    resolution: str = "720p", ratio: str = "16:9",
    images: list[str] | None = None, videos: list[str] | None = None,
    audios: list[str] | None = None, start_image: str | None = None,
    end_image: str | None = None, mode: str = "auto",
    generate_audio: bool | None = None,
) -> PreparedRequest:
    spec = model_spec(model, "video")
    if not isinstance(prompt, str):
        raise ContractError("Prompt must be text")
    seedance25 = model == "seedance-2.5"
    grok = model == "grok-imagine-video-1.5"
    limits = (7, 0, 0, 7) if grok else (30, 10, 10, 50) if seedance25 else (9, 3, 3, 12)
    image_refs = references(images, limits[0])
    video_refs = references(videos, limits[1])
    audio_refs = references(audios, limits[2])
    total = len(image_refs) + len(video_refs) + len(audio_refs)
    if total > limits[3]:
        raise ContractError("Combined reference limit exceeded")
    if end_image and (not start_image or grok):
        raise ContractError("An end frame requires a Seedance start frame")
    if start_image and total:
        raise ContractError("Start/end frames cannot be combined with references")
    if not prompt.strip() and not (start_image or total):
        raise ContractError("Prompt is required without media")
    if not grok and len(prompt.encode("utf-8")) > 40000:
        raise ContractError("Seedance prompt exceeds 40000 UTF-8 bytes")
    if mode not in ("auto", "reference", "edit") or (mode != "auto" and not seedance25):
        raise ContractError("Reference/edit mode is specific to Seedance 2.5")
    if mode == "edit":
        if not video_refs or not prompt.strip() or start_image or end_image or duration != -1 or type(duration) is not int or ratio != "adaptive":
            raise ContractError("Edit requires a video, prompt, duration=-1 and adaptive ratio")
    else:
        integer(duration, 1 if grok else 4, 30 if seedance25 else 15, "duration")
    resolutions = ("480p", "720p", "1080p", "4k") if model == "seedance-2.0" else ("480p", "720p", "1080p")
    if resolution not in resolutions or (
        grok and (image_refs or start_image) and resolution == "1080p"
    ):
        raise ContractError("Unsupported resolution for this model/mode")
    ratios = BASE_RATIOS + (("3:2", "2:3") if grok else ("21:9",))
    if seedance25 and (start_image or mode == "edit"):
        if ratio != "adaptive":
            raise ContractError("Seedance 2.5 frame/edit mode requires adaptive ratio")
    elif ratio not in ratios:
        raise ContractError("A fixed supported ratio is required for text/reference video")
    if model == "seedance-2.0" and audio_refs and not (image_refs or video_refs):
        raise ContractError("Seedance 2.0 audio requires image/video references")
    if generate_audio is not None and (type(generate_audio) is not bool or not generate_audio or grok):
        raise ContractError("This provider cannot disable Seedance audio or configure Grok audio")
    payload: dict[str, Any] = {
        "model": spec.id, "prompt": prompt, "duration": duration,
        "resolution": resolution, "aspect_ratio": ratio, "n": 1,
    }
    for name, refs in (("reference_images", image_refs), ("reference_videos", video_refs), ("reference_audios", audio_refs)):
        if refs:
            payload[name] = [{"url": url} for url in refs]
    if start_image:
        payload["image" if grok else "start_image"] = {"url": media_url(start_image)}
    if end_image:
        payload["end_image"] = {"url": media_url(end_image)}
    if mode != "auto":
        payload["omni_reference_task_type"] = mode
    if generate_audio is not None:
        payload["generate_audio"] = generate_audio
    return prepared(spec.endpoint, key, payload)


def image_request(
    model: str, prompt: str, *, key: str, images: list[str] | None = None,
    ratio: str = "1:1", resolution: str = "2k", quality: str = "auto", n: int = 1,
    size: str | None = None, mask: str | None = None,
) -> PreparedRequest:
    spec = model_spec(model, "image")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ContractError("Image prompt is required")
    gpt = model == "gpt-image-2.5-sunburst"
    pro = model == "nano-banana-pro"
    refs = references(images, 16 if gpt else 14 if pro else 3, allow_data=True)
    integer(n, 1, 7 if gpt else 4, "n")
    resolution = str(resolution).lower()
    # NB2 4K is explicitly documented in its own example and published tariff.
    if resolution not in ("1k", "2k", "4k"):
        raise ContractError("Unsupported image resolution")
    payload: dict[str, Any] = {"model": model, "prompt": prompt, "n": n, "response_format": "b64_json"}
    if gpt:
        if quality not in ("auto", "low", "medium", "high"):
            raise ContractError("Unsupported GPT image quality")
        if size is None:
            if ratio == "auto":
                size = "auto"
            else:
                if not re.fullmatch(r"[1-9][0-9]?:[1-9][0-9]?", ratio):
                    raise ContractError("Image ratio must be W:H or auto")
                w, h = (int(x) for x in ratio.split(":"))
                side = {"1k": 1024, "2k": 2048, "4k": 3840}[resolution]
                size = f"{round(side * w / max(w, h))}x{round(side * h / max(w, h))}"
        if size != "auto" and not re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*", size):
            raise ContractError("GPT image size must be auto or positive WIDTHxHEIGHT")
        payload.update(size=size, quality=quality)
        if mask:
            if not refs:
                raise ContractError("A mask requires an input image")
            payload["mask"] = {"image_url": media_url(mask, allow_data=True)}
    else:
        allowed = BASE_RATIOS + (("3:2", "2:3", "5:4", "4:5", "21:9") if pro else ())
        if ratio not in allowed or size is not None or mask is not None:
            raise ContractError("Unsupported Nano image ratio/size/mask")
        payload.update(aspect_ratio=ratio, resolution=resolution)
    if refs:
        payload["images"] = [{"image_url": url} for url in refs]
    return prepared("/v1/images/edits" if refs else spec.endpoint, key, payload)


def text_request(
    model: str, prompt: str, *, key: str, instructions: str = "",
    images: list[str] | None = None, max_output_tokens: int = 4096,
    reasoning_effort: str | None = None,
) -> PreparedRequest:
    spec = model_spec(model, "text")
    if not isinstance(prompt, str) or not prompt.strip() or not isinstance(instructions, str):
        raise ContractError("Text prompt and instructions must be strings")
    integer(max_output_tokens, 1, 128000, "max_output_tokens")
    # Vision counts are product input limits, not an inferred upstream guarantee.
    refs = references(images, 16, allow_data=True)
    if model == "grok-4.5" and reasoning_effort is not None:
        raise ContractError("No Grok reasoning effort contract is configured")
    if model == "glm-5.3-flash":
        content: Any = prompt
        if refs:
            content = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": url}} for url in refs]
        messages: list[dict[str, Any]] = []
        if instructions:
            messages.append({"role": "system", "content": instructions})
        messages.append({"role": "user", "content": content})
        payload: dict[str, Any] = {"model": model, "messages": messages, "max_completion_tokens": max_output_tokens}
        if reasoning_effort is not None:
            if reasoning_effort not in ("high", "max", "low", "medium", "xhigh"):
                raise ContractError("Unsupported GLM reasoning effort")
            payload["reasoning_effort"] = reasoning_effort
    else:
        input_value: Any = prompt
        if refs:
            input_value = [{"role": "user", "content": [{"type": "input_text", "text": prompt}] + [{"type": "input_image", "image_url": url} for url in refs]}]
        payload = {"model": model, "input": input_value, "max_output_tokens": max_output_tokens}
        if instructions:
            payload["instructions"] = instructions
        if reasoning_effort is not None:
            if reasoning_effort not in ("low", "medium", "high", "xhigh", "max"):
                raise ContractError("Unsupported Luna reasoning effort")
            payload["reasoning"] = {"effort": reasoning_effort}
    return prepared(spec.endpoint, key, payload)
