from __future__ import annotations

import logging
import time
from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import PhotoSize


logger = logging.getLogger(__name__)

TEMP_PHOTOS_DIR = Path("temp/photos")
DEFAULT_MAX_AGE_SECONDS = 60 * 60


async def save_temp_photo(bot: Bot, photo: PhotoSize) -> Path:
    TEMP_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    destination = TEMP_PHOTOS_DIR / f"{uuid4().hex}.jpg"

    try:
        await bot.download(photo, destination=destination)
    except Exception:
        delete_temp_file(destination)
        raise

    logger.info("Temporary photo saved: %s", destination)
    return destination


def delete_temp_file(path: Path | str) -> bool:
    file_path = Path(path)
    if not _is_temp_photo_path(file_path):
        logger.warning("Refusing to delete file outside temp photo directory: %s", file_path)
        return False

    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Failed to delete temporary file: %s", file_path)
        return False

    logger.info("Temporary file deleted: %s", file_path)
    return True


def cleanup_old_temp_files(max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS) -> int:
    TEMP_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    cutoff_timestamp = time.time() - max_age_seconds
    deleted_count = 0

    for file_path in TEMP_PHOTOS_DIR.iterdir():
        if not file_path.is_file():
            continue

        try:
            if file_path.stat().st_mtime >= cutoff_timestamp:
                continue
        except OSError:
            logger.exception("Failed to stat temporary file during cleanup: %s", file_path)
            continue

        if delete_temp_file(file_path):
            deleted_count += 1

    logger.info(
        "Temporary photo cleanup completed: deleted=%s max_age_seconds=%s directory=%s",
        deleted_count,
        max_age_seconds,
        TEMP_PHOTOS_DIR,
    )
    return deleted_count


def _is_temp_photo_path(path: Path) -> bool:
    temp_dir = TEMP_PHOTOS_DIR.resolve()
    resolved_path = path.resolve(strict=False)
    return resolved_path == temp_dir or temp_dir in resolved_path.parents
