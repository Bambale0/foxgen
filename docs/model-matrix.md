# KIE.ai model matrix

FoxGen treats the KIE catalog as a versioned provider contract, not a list of marketing names. Discovering a provider model does **not** automatically make it safe for paid submission.

## Independent readiness fields

Every model returned by `GET /v1/models` exposes:

- `provider_id_verified` — the exact KIE provider identifier and API family were checked;
- `schema_verified` — FoxGen has a strict reviewed request schema for the supported subset;
- `enabled_for_submission` — paid task admission is allowed;
- `tested_live` — a credentialed provider smoke test was recorded;
- `production_ready` — provider ID, schema and submission gate are all true;
- `contract_reviewed_at` — date of the latest explicit contract review.

`tested_live=false` is not hidden or inferred. It remains false until a real provider request is run in a controlled environment and recorded.

## Production-enabled Market models

| FoxGen slug | KIE model | Supported subset | Local validation |
|---|---|---|---|
| `seedream-5-pro` | `seedream/5-pro-text-to-image` | text to image | strict prompt, ratio, quality and output-format enums |
| `seedream-5-pro-edit` | `seedream/5-pro-image-to-image` | image editing | strict text contract plus 1–10 image URLs |
| `nano-banana-2` | `nano-banana-2` | text generation and image editing | strict ratio, resolution and output-format enums; FoxGen cap of 14 images |
| `nano-banana-pro` | `nano-banana-pro` | text generation and image editing | same reviewed normalized contract with the Pro provider ID |
| `seedance-2` | `bytedance/seedance-2` | text, first/last frame and multimodal references | strict ratio, resolution and duration enums; mutually exclusive generation modes |
| `seedance-2-mini` | `bytedance/seedance-2-mini` | same supported subset as Seedance 2 | same reviewed schema with the Mini provider ID |

The Seedance contract additionally requires a first frame when a last frame is supplied. FoxGen accepts at most six multimodal references in total. Individual list limits and media-count caps are conservative FoxGen safety limits; they are not presented as provider-wide maxima.

`Seedance 2 Fast` is intentionally excluded from the active FoxGen registry. The product priority is the full Seedance 2 model plus Seedance 2 Mini.

## Catalog-only models

The catalog also contains provider IDs and capability metadata for Seedream 4.5, GPT Image 2, Flux 2 Pro, Imagen 4 Ultra, Ideogram V3, Qwen2, Wan 2.7, Grok Imagine, Kling, Hailuo, Topaz, Recraft and ElevenLabs operations.

These entries remain useful for discovery and roadmap planning, but their paid submission gate stays off until their exact model-specific schema is reviewed. Generic `PROMPT`, `PROMPT_IMAGES`, media-category and `PASSTHROUGH` contracts are not considered production schemas.

A request to a catalog-only model is rejected before rate limiting, persistence, balance reservation, outbox creation or KIE access.

## API behavior

- `GET /v1/models` returns catalog metadata and independent readiness fields.
- `GET /v1/models/{slug}` also returns the current JSON schema.
- `POST /v1/models/{slug}/validate` performs free local schema validation.
- `POST /v1/models/{slug}/tasks` admits only `production_ready` models and validates again before the atomic billing transaction.

## Models intentionally not sent through the Market adapter

Veo 3.1, Runway/Aleph, Suno music operations, Gemini Omni resource creation and current chat endpoints use dedicated paths and response formats. They remain separate adapters; routing them through `/api/v1/jobs/createTask` would be incorrect.

## Maintenance and drift review

Before enabling a new model or version:

1. verify the exact provider ID and API family in official KIE documentation;
2. record the documentation page and review date;
3. implement a strict model-specific schema with enum, range and cross-field rules;
4. add valid provider-example fixtures and invalid boundary tests;
5. ensure no enabled entry uses passthrough or broad open validation;
6. run a controlled live smoke test when credentials and budget are available;
7. update this matrix and recommendation order.

Contract review is required whenever the provider documentation changes, a live request starts returning a previously unseen validation error, or six months pass since `contract_reviewed_at`.
