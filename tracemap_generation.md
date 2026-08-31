# HappyFox generation tracemap

## Shared domain

```text
channel input
 -> identity/user context
 -> normalized generation request
 -> pricing/billing decision
 -> durable task/job
 -> provider adapter
 -> provider task ID/status
 -> result URL/media
 -> delivery/history
```

Telegram and Instagram must converge on shared provider/pricing/data services rather than duplicating generation implementations.

## Telegram photo/video

```text
Telegram handler or Mini App API
 -> validate model/options/references
 -> shared pricing
 -> deduct balance
 -> generation task/history
 -> provider service
 -> webhook/polling
 -> result delivery
 -> refund on terminal failure when applicable
```

The Telegram model catalog is broader and is driven by runtime model/pricing configuration.

## Instagram entry

```text
Instagram webhook
 -> bot/instagram_api.py normalize + HMAC/idempotency
 -> channel identity
 -> bot/instagram_creator_generation.py
 -> Photo or Video branch
```

If no creation type is selected, media must not start generation.

## Instagram photo

```text
Photo
 -> Seedream 5 Pro High
 -> seedream/5-pro-image-to-image
 -> 1:1
```

First photo:

```text
reference -> prompt
 -> reserve instagram_first_image promotion
 -> durable job prepared/queued
 -> create provider task
 -> persist provider_task_id
 -> poll/resume same task
 -> persist result_url
 -> send image to Direct
 -> persist delivered checkpoint
 -> consume promotion
```

Terminal provider failure before success:

```text
job failed -> release promotion -> free attempt remains available
```

Later photo:

```text
reference -> prompt -> 2.5 🐾 confirm
 -> deduct once
 -> durable job/provider
 -> result
```

Terminal paid failure -> refund once.

## Instagram video

```text
Video selected
 -> paid top-up state BEFORE media
 -> Continue/Продолжить + linked balance check
 -> reference (photo or video)
 -> prompt
 -> Seedance 2.5 price confirmation
 -> charge
 -> durable job
 -> bytedance/seedance-2-5
 -> 720p / 9:16
 -> result delivery
```

Video has no free path.

## Durable job recovery

```text
prepared -> queued -> processing -> result persisted -> delivered/finalized
```

Recovery invariants:

- provider task ID exists -> retry polls same task, no duplicate submit;
- result URL exists -> retry delivery, no regeneration;
- delivered checkpoint exists -> later finalization retry skips intentional re-send;
- paid failure -> refund exactly once;
- free-photo failure -> promotion release exactly once.

## Relevant modules

```text
bot/instagram_model_contract.py
bot/instagram_creator_generation.py
bot/instagram_seedream_generation.py
bot/instagram_video_generation.py
bot/instagram_generation.py
bot/channel_promotions.py
bot/services/*
bot/database.py
```

## Regression evidence

Important tests:

```text
tests/test_instagram_creator_flow.py
tests/test_instagram_generation.py
tests/test_instagram_model_contract.py
tests/test_channel_promotions.py
```
