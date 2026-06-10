from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import PhotoSize


logger = logging.getLogger(__name__)

IMAGES_DIR = Path("images")


async def save_product_photo(bot: Bot, photo: PhotoSize) -> str:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.jpg"
    destination = IMAGES_DIR / filename

    await bot.download(photo, destination=destination)
    logger.info("Product photo saved: %s", destination)
    return str(destination)
