# KIE.ai model matrix

FoxGen treats the KIE catalog as a versioned provider contract, not a list of marketing names. Every enabled entry has an exact provider `model` identifier, an official documentation page, capabilities, defaults and an input-contract level.

## Integration levels

- **Strict contract** — model-specific Pydantic schema, defaults and cross-field validation.
- **Documented contract** — exact provider ID and capability are verified; a reusable preflight schema validates the required media category while allowing documented provider-specific fields.
- **Dedicated adapter required** — the model does not use the Market `createTask` protocol and must not be routed through the generic adapter.

## Priority models — strict contracts

| FoxGen slug | KIE model | Modes | Important validation |
|---|---|---|---|
| `seedance-2` | `bytedance/seedance-2` | text, first/last frame, multimodal references | frame mode and multimodal-reference mode are mutually exclusive |
| `seedance-2-fast` | `bytedance/seedance-2-fast` | same as Seedance 2 | same contract, optimized tier |
| `seedance-2-mini` | `bytedance/seedance-2-mini` | same as Seedance 2 | same contract, budget tier |
| `seedream-5-pro` | `seedream/5-pro-text-to-image` | text to image | prompt, ratio, quality, output format, NSFW checker |
| `seedream-5-pro-edit` | `seedream/5-pro-image-to-image` | image generation/edit | requires at least one `image_urls` value |
| `nano-banana-2` | `nano-banana-2` | text generation and image edit | empty `image_input` means text mode |
| `nano-banana-pro` | `nano-banana-pro` | text generation and image edit | same normalized contract with Pro provider ID |
| `kling-3` | `kling-3.0/video` | single/multi-shot, element references | single shot requires prompt; multi-shot requires shot array |

## Current Market flagship pack

### Image

Seedream 5 Pro, Nano Banana 2/Pro, GPT Image 2, Flux 2 Pro, Imagen 4 Ultra, Ideogram V3, Qwen2, Wan 2.7 Image Pro, Grok Imagine, Topaz and Recraft enhancement tools.

### Video

Seedance 2/ Fast / Mini, Kling 3.0 and V3 Turbo, Wan 2.7 text/image/reference/edit flows, Grok Imagine Video, Hailuo 2.3 Pro and Topaz Video Upscale.

### Voice and audio

ElevenLabs Dialogue V3, Multilingual V2, Turbo 2.5 and Audio Isolation.

The full machine-readable list is returned by `GET /v1/models`. `GET /v1/models/{slug}` returns the JSON schema required to build Telegram FSM steps or a web form dynamically. `POST /v1/models/{slug}/validate` performs free local preflight validation. `POST /v1/models/{slug}/tasks` validates again and submits the exact provider ID to KIE.

## Models intentionally not sent through the Market adapter

Veo 3.1, Runway/Aleph, Suno music operations, Gemini Omni resource creation and current chat endpoints use dedicated paths and response formats. They remain separate adapters; routing them through `/api/v1/jobs/createTask` would be incorrect. Their implementation is tracked under the provider and product epics.

## Maintenance rule

Before enabling a new model or version:

1. verify the exact provider ID and endpoint in official KIE documentation;
2. record its capability and API family;
3. add or select an input contract;
4. add a contract test that asserts the outbound model ID;
5. update this matrix and the user-facing recommendation order.
