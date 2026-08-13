# KIE.ai model matrix and readiness policy

FoxGen treats every provider model as a reviewed contract, not a marketing-name string. Discovering a KIE model does not automatically authorize paid submission.

This document describes the current registry policy in `main`. Exact provider behavior should be re-verified against official KIE documentation whenever a contract is changed or enabled.

## Readiness fields

Every model exposed by `GET /v1/models` carries independent readiness metadata:

- `provider_id_verified` — exact provider identifier/API family reviewed;
- `schema_verified` — strict FoxGen request schema reviewed for the supported subset;
- `enabled_for_submission` — code-level paid-admission allowlist permits it;
- `tested_live` — controlled credentialed provider smoke test recorded;
- `production_ready` — provider ID/schema/submission readiness satisfy the registry rule;
- `contract_reviewed_at` — explicit review date;
- capabilities/defaults/recommendation metadata.

`tested_live=false` must remain visible until a real test has happened; it is not inferred from contract unit tests.

## Runtime administrative availability

A model can be structurally `production_ready` in the registry while being administratively disabled at runtime.

Paid admission therefore has two separate gates:

```text
registry readiness
AND
runtime ModelAvailability/admin policy
```

`POST /internal/admin/models/{model_slug}/availability` can disable/re-enable a model without application deployment. The runtime guard is enforced before transactional paid admission, not merely hidden in Telegram UI.

Use runtime disable for provider incidents/emergency containment. Use registry contract changes when the underlying supported schema/provider ID changes.

## Strict production-enabled Market models

| FoxGen slug | KIE provider model | Supported FoxGen subset |
|---|---|---|
| `seedream-5-pro` | `seedream/5-pro-text-to-image` | text-to-image with strict prompt/ratio/quality/output-format validation |
| `seedream-5-pro-edit` | `seedream/5-pro-image-to-image` | image editing with strict text contract and bounded image URL list |
| `nano-banana-2` | `nano-banana-2` | text generation/image editing with reviewed ratio/resolution/output-format contract |
| `nano-banana-pro` | `nano-banana-pro` | Pro provider ID with the reviewed normalized Nano Banana contract |
| `seedance-2` | `bytedance/seedance-2` | text, first/last-frame and multimodal-reference video subset |
| `seedance-2-mini` | `bytedance/seedance-2-mini` | same reviewed supported mode family with Mini provider ID |

The Seedance contract enforces mutually compatible generation modes and requires a first frame when a last frame is supplied. Conservative FoxGen reference/image caps are product safety limits, not claims about the provider's global maximum.

`Seedance 2 Fast` is not part of the active FoxGen production registry baseline documented here.

## Catalog-only entries

The registry/catalog also contains provider metadata for additional families such as:

- Seedream 4.5;
- GPT Image 2;
- Flux 2 Pro;
- Imagen 4 Ultra;
- Ideogram V3;
- Qwen2;
- Wan 2.7;
- Grok Imagine;
- Kling;
- Hailuo;
- Topaz;
- Recraft;
- ElevenLabs operations.

Catalog presence is useful for roadmap/discovery but does not make a model billable. A broad/generic `PASSTHROUGH` or category schema is not accepted as a production paid contract.

A catalog-only task request is rejected before billing reservation/outbox/provider access.

## Dedicated API families

Some KIE products do not belong to the generic Market `createTask` adapter and must use dedicated adapters/contracts when implemented, including families with materially different create/status/resource semantics such as:

- Veo;
- Runway/Aleph;
- Suno music operations;
- Gemini Omni resource flows;
- chat endpoints.

Do not route a model through the generic Market adapter merely to make it fit the existing task endpoint.

## API semantics

```text
GET  /v1/models
GET  /v1/models/{slug}
POST /v1/models/{slug}/validate
POST /v1/models/{slug}/tasks
```

- list/detail expose catalog/readiness metadata;
- detail includes current local input schema;
- `/validate` is free local validation;
- `/tasks` revalidates the contract and all paid-admission gates;
- runtime administrative disable is checked before durable paid admission.

## Telegram compatibility

Telegram handlers select product capabilities/modes, not arbitrary provider payload dictionaries. The current image/video FSM exposes only combinations intentionally mapped to supported contracts.

Quick Start reference routing also selects compatible models based on the requested output and reference media kind. Unsupported reference/model combinations are rejected before billing.

## Contract review procedure

Before enabling/changing a model:

1. verify exact provider model ID and API family in official KIE documentation;
2. record/review provider documentation and date;
3. implement a strict model-specific input contract;
4. define cross-field rules, enums and numeric/list bounds;
5. add valid fixtures based on reviewed provider examples;
6. add invalid/boundary tests;
7. make sure no paid-enabled entry relies on open passthrough validation;
8. update bot mode/model mapping if the product flow changes;
9. run controlled live smoke test when credentials/budget are available;
10. set/retain readiness flags truthfully;
11. update this matrix and any pricing/admin documentation.

## Drift triggers

Re-review a contract when:

- provider documentation changes;
- a previously valid request starts receiving new provider validation errors;
- result/callback shape changes;
- provider model ID/version changes;
- a runtime incident requires repeated disabling;
- the explicit review period expires under project policy.

During uncertain drift, prefer runtime disable + investigation over loosening validation.

## Billing interaction

A production-ready, runtime-enabled model still needs an active price and sufficient balance. Model readiness never implies a default commercial price.

The final admission condition is effectively:

```text
trusted caller
+ valid user/idempotency
+ strict model contract
+ registry production readiness
+ runtime availability
+ rate/concurrency allowance
+ active price
+ sufficient wallet
=> atomic local admission
```

## Source-of-truth rule

When this document conflicts with current registry/contracts/tests, treat executable contract code/tests as authoritative and fix this document. Never change provider IDs based only on this Markdown file.