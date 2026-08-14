# Feed, public profiles and remix

FoxGen publication state is deliberately separate from the durable generation lifecycle. A generation remains the immutable source of truth for provider/billing/delivery state; a publication is a reversible social projection of a completed generation.

## Domain map

```text
users
  └─ public_profiles (1:1 sidecar)

generations
  ├─ media_assets
  ├─ publications (feed/profile, independently active)
  └─ generation_lineage (optional derivative source)

publications
  ├─ publication_likes (publication,user unique)
  └─ publication_comments (surface-scoped)
```

### Public profiles

`public_profiles` stores only public presentation fields:

- stable slug;
- optional display name;
- optional bio.

Identity remains in `users`. Profile state never owns balance, generation or provider state.

### Publications

A publication identifies one generation and one surface:

- `feed` — global discovery feed;
- `profile` — author's public profile.

`(generation_id, scope)` is unique. Publishing the same generation/scope again reactivates the existing row instead of duplicating the post. Unpublish marks the publication inactive; it does not mutate or delete the generation or result media.

## Publication eligibility

Publication fails closed unless all conditions are true:

1. the generation belongs to the authenticated user;
2. generation status is `succeeded`;
3. at least one result `media_asset` exists;
4. every required media asset is `stored`;
5. a derivative generation is not being published to the global `feed`.

A derivative may be published to the author's `profile`, but its public projection always hides the generation prompt and disables prompt/remix actions.

## Remix lineage

A remix is a normal paid generation with an additional immutable source marker.

Telegram flow:

```text
publication
  -> request remix source
  -> choose compatible model/settings
  -> confirmation
  -> revalidate source + get fresh signed result URLs
  -> paid admission with X-FoxGen-Source-Publication-Id
```

The source publication ID is part of the submission fingerprint. `SqlAlchemyGenerationRepository.admit()` validates that the source publication is still active and inserts `generation_lineage` in the same PostgreSQL transaction as balance reservation and generation submit outbox creation. This prevents a billable derivative from being committed without its lineage marker.

The source ID is internal FoxGen metadata. It is not inserted into the KIE provider payload and does not change model pricing.

### No remix chains from derivatives

Public derivative projections set:

```text
prompt = null
prompt_actions_allowed = false
```

`remix_source()` also rejects a derivative publication server-side. UI hiding is therefore not the security boundary.

## Media privacy

Publication rows do not copy provider result URLs. `media_assets.storage_key` remains the durable result reference.

Telegram/trusted clients obtain media through the authenticated publication-media endpoint, which creates short-lived S3-compatible presigned GET URLs. Storage credentials and permanent object URLs are never exposed.

Temporary Telegram inputs and publication results use different storage contracts:

- temporary incoming references — local shared input storage under the current bot/API topology;
- durable generated results — S3-compatible storage under `generations/`.

Remix confirmation requests fresh signed durable-result URLs immediately before paid admission; it does not pretend a `generations/` object is a local temporary input.

## Feed reads

`GET /v1/feed` supports:

- `recent` — newest first;
- `top_day` — posts created in the previous day, ranked by engagement;
- `top` — all active feed publications ranked by engagement.

Current deterministic score uses likes, comments and remix count. Pagination is explicit `limit`/`offset` and bounded server-side.

## Likes

Like state is setting-based, not toggle-based:

```text
PUT /v1/publications/{id}/like
{"liked": true|false}
```

The `(publication_id, user_id)` primary key makes repeated `liked=true` idempotent. Repeated `liked=false` deletes an already-absent row harmlessly. The count is read after the state change, so concurrent clients do not increment/decrement a cached counter manually.

## Comments

Comments carry an explicit surface:

```text
feed | profile
```

The service verifies that the requested comment surface matches the publication's surface before write/read. A feed thread cannot be read as a profile thread or vice versa.

Comments are currently flat chronological messages; nested replies are not part of issue #58.

## HTTP surface

Authenticated user-context endpoints:

```text
GET    /v1/feed
GET    /v1/publications/{publication_id}
GET    /v1/publications/{publication_id}/media
GET    /v1/publications/{publication_id}/remix
PUT    /v1/publications/{publication_id}/like
GET    /v1/publications/{publication_id}/comments
POST   /v1/publications/{publication_id}/comments

GET    /v1/profiles/{slug}
GET    /v1/profiles/{slug}/publications
GET    /v1/me/profile
PUT    /v1/me/profile
GET    /v1/me/publications

POST   /v1/generations/{generation_id}/publications
DELETE /v1/generations/{generation_id}/publications/{scope}
```

These endpoints use the existing trusted Bearer token plus `X-FoxGen-User-Id`. Username, when supplied by the trusted Telegram service, is presentation metadata only and never replaces authenticated user ID.

Paid remix admission additionally uses:

```text
X-FoxGen-Source-Publication-Id: <publication UUID>
```

## Telegram UI

Main menu includes:

- `🌐 Лента`;
- `👤 Профиль`;
- `📣 Опубликовать генерацию`.

The feed renders one publication card at a time with recent/top-day/top navigation, author, engagement actions and remix when allowed. Profile flow exposes profile publications and own-publication management. The publish wizard accepts a generation UUID and then asks for `feed` or `profile` scope; the server still enforces completion/media/derivative rules.

### Global `/start` rule

`foxgen-global-commands` is the first Telegram router. `/start` and `/menu` always clear the current FSM before any state-specific handler can consume the command. This includes both `GenerationStates` and `FeedStates`.

For `/start <payload>`, cleanup happens first and only then is the recognized deep link dispatched. Therefore a post/profile/remix link is also a deterministic state transition from any existing flow.

Supported start payloads:

```text
post_<publication UUID>
profile_<public slug>
remix_<publication UUID>
```

Telegram start payloads are limited to 64 characters. Product-facing profile slugs are therefore constrained so `profile_<slug>` remains inside that boundary.

## Migration and rollback

Migration `20260814_0009_publication_feed` creates publication/profile/lineage/like/comment tables only. It does not rewrite existing generation or billing rows.

Downgrade removes social rows and lineage. Before downgrading a production system that already created remix generations, understand that removing lineage also removes the server-side marker used to distinguish derivatives from originals. Do not downgrade while derivative publication safety is required without an equivalent migration/feature rollback plan.

## Explicit compromises for issue #58

The implementation intentionally does **not** claim the following:

- no public React Mini App feed is shipped; Telegram is the required product UI for this issue;
- feed ranking is deterministic engagement ranking, not a personalized recommendation model;
- comments are flat, not threaded/reply trees;
- publication media is linked to existing durable `media_assets`; it is not copied into a separate social CDN/object namespace;
- publication management is intentionally reversible `active` state, not destructive deletion;
- Telegram publish wizard may use the generation UUID shown by FoxGen instead of relying on a public Mini App generation gallery;
- profile slugs are constrained by Telegram deep-link payload length rather than using a second opaque profile-link identifier.

These are bounded product choices, not hidden gaps in generation billing/provider correctness.

## Regression requirements

A change to this domain is incomplete unless tests preserve:

- migration upgrade/downgrade;
- publication only after `succeeded` + all media `stored`;
- ownership checks;
- unique/idempotent publication per generation/scope;
- derivative global-feed rejection;
- derivative prompt/action redaction;
- idempotent like/unlike;
- comment surface isolation;
- deep-link parser limits;
- `/start` interruption for every declared generation/feed FSM state;
- remix source in submission fingerprint and transactional lineage;
- fresh private media URLs at final remix confirmation.
