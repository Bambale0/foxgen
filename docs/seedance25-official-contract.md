# Seedance 2.5 — production contract

HappyFox uses KIE model `bytedance/seedance-2-5` through `POST /api/v1/jobs/createTask`.

## Public flows

1. Text → video.
2. First frame → video.
3. First + last frame → video.
4. Multimodal reference → video with image, video and/or audio references.

The three media-backed modes are mutually exclusive. First-frame modes use `aspect_ratio=adaptive` so output follows the supplied frame.

## Product controls

- duration: 4–30 seconds;
- resolution: 480p / 720p;
- aspect ratio: adaptive, 16:9, 9:16, 1:1, 4:3, 3:4, 21:9 (frame modes are forced to adaptive);
- native audio generation;
- optional last-frame return;
- image/video/audio references;
- callback URL with polling reconciliation as fallback.

Pricing stays in the existing `seedance_2_5` admin price configuration and is read at launch time.

The current KIE Seedance 2.5 request surface does not expose the old HappyFox `web_search`, `nsfw_checker`, `output_format`, or admin-only auto-duration controls, so those controls are intentionally not sent by this integration.
