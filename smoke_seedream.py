#!/usr/bin/env python3
"""Smoke test: Seedream 5 Pro image-to-image with a real reference image.

Tests the EXACT code path that production uses:
  seedream_service.generate_image() -> _prepare_effective_image_urls()
  -> kie_file_upload_service.upload_local_image_sources(prefer_stable_public_url=True)

This should reproduce the "Timeout while downloading url" error.
"""

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("smoke_seedream")

from bot.config import config
from bot.services.seedream_service import seedream_service

REF_IMAGE_REL = "uploads/refs/image/1004481637/202607/654d597b632e63a217837e23def5a61f.jpg"
REF_IMAGE_URL = f"{config.static_base_url.rstrip('/')}/{REF_IMAGE_REL}"

PROMPT = "A beautiful woman with flowing hair, cinematic lighting, photorealistic, 8k quality"


async def run_smoke_test():
    logger.info("=== SMOKE TEST: Seedream 5 Pro image-to-image ===")
    logger.info("Reference URL: %s", REF_IMAGE_URL)
    logger.info("Prompt: %s", PROMPT)

    local_path = os.path.join("static", REF_IMAGE_REL)
    if os.path.exists(local_path):
        size = os.path.getsize(local_path)
        logger.info("Local file exists: %s (%d bytes)", local_path, size)
    else:
        logger.error("Local file NOT FOUND: %s", local_path)
        return

    logger.info("Calling seedream_service.generate_image() ...")
    start = time.time()
    result = await seedream_service.generate_image(
        prompt=PROMPT,
        image_urls=[REF_IMAGE_URL],
        aspect_ratio="1:1",
        quality="basic",
        model="seedream/5-pro-image-to-image",
    )
    elapsed = time.time() - start
    logger.info("generate_image returned in %.2fs", elapsed)

    if not result:
        logger.error("Result is None")
        return

    if result.get("error"):
        logger.error("Task creation FAILED: error=%s message=%s", result.get("error"), result.get("message"))
        logger.error("Full result: %s", result)
        return

    task_id = result.get("task_id")
    if not task_id:
        logger.error("No task_id in result: %s", result)
        return

    logger.info("Task created: task_id=%s", task_id)
    logger.info("Raw response: %s", result.get("raw"))

    logger.info("Polling for task status (up to 3 min)...")
    for attempt in range(36):
        await asyncio.sleep(5)
        status = await seedream_service.get_task_status(task_id)
        if not status:
            logger.info("  attempt %d: no status yet", attempt + 1)
            continue

        task_status = status.get("data", {}).get("status", "unknown")
        output = status.get("data", {}).get("output")
        logger.info("  attempt %d: status=%s output=%s", attempt + 1, task_status, output)

        if task_status in ("completed", "succeeded", "success"):
            logger.info("SUCCESS! Output: %s", output)
            return
        if task_status in ("failed", "error"):
            logger.error("TASK FAILED! Raw: %s", status.get("raw"))
            return

    logger.warning("Timed out after 3 minutes")


if __name__ == "__main__":
    asyncio.run(run_smoke_test())