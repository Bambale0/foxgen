# KIE.ai model matrix

The KIE.ai catalog changes over time. FoxGen separates product families from exact provider model IDs. A model becomes enabled only after its official request schema, result schema and error behavior have contract tests.

## Verified in the foundation PR

| Product | Provider model | Capability |
|---|---|---|
| GPT Image 2 | `gpt-image-2-text-to-image` | text to image |
| GPT Image 2 Edit | `gpt-image-2-image-to-image` | image to image/edit |
| Grok Imagine Image | `grok-imagine/text-to-image` | text to image |
| Qwen Image | `qwen/text-to-image` | text to image |
| Recraft Crisp Upscale | `recraft/crisp-upscale` | image upscale |
| Grok Imagine Video | `grok-imagine/text-to-video` | text to video |

## Integration queue

The following top families are tracked by EPIC 03 and EPIC 05:

- Images: Nano Banana 2/Pro, Seedream 4.5/5, Flux 2/Kontext, Ideogram, Imagen 4, Wan Image, Topaz and background removal.
- Video: Kling 3, Kling Motion Control/Avatar, Seedance 2, Veo 3.1, Runway/Aleph, Wan 2.7, Hailuo, PixVerse, HappyHorse, OmniHuman and Topaz Video.
- Audio/music: ElevenLabs, Gemini TTS and Suno generation/editing/stems/MIDI.
- Chat: current KIE GPT chat endpoints for Prompt AI and the assistant.

Do not enable an entry based only on a model name. Verify the exact `model` value and all payload constraints in official KIE.ai documentation first.
