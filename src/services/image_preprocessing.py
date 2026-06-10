from __future__ import annotations

import logging
from pathlib import Path


logger = logging.getLogger(__name__)


def prepare_ocr_images(image_path: Path) -> list[object]:
    """Return preprocessed image variants for OCR, label crop first."""
    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError as exc:
        logger.exception("OCR image dependencies are not installed")
        raise RuntimeError("opencv-python and Pillow are required for OCR") from exc

    with Image.open(image_path) as source:
        source = ImageOps.exif_transpose(source).convert("RGB")
        rgb = np.array(source)

    label_crop = crop_label(rgb)
    variants: list[object] = []

    for image in (label_crop, rgb):
        variants.extend(preprocess_for_ocr(image))

    logger.info("Prepared OCR image variants: %s", len(variants))
    return variants


def crop_label(rgb_image: object) -> object:
    import cv2

    gray = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    threshold = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        7,
    )
    inverted = cv2.bitwise_not(threshold)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 7))
    closed = cv2.morphologyEx(inverted, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = gray.shape[:2]
    image_area = width * height

    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < image_area * 0.04 or area > image_area * 0.95:
            continue

        aspect_ratio = w / max(h, 1)
        if aspect_ratio < 1.2 or aspect_ratio > 8:
            continue

        rectangularity = area / max(cv2.contourArea(contour), 1)
        score = area * min(aspect_ratio, 4) / rectangularity
        candidates.append((score, (x, y, w, h)))

    if not candidates:
        logger.info("Label contour not found, using full image")
        return rgb_image

    _, (x, y, w, h) = max(candidates, key=lambda item: item[0])
    padding_x = int(w * 0.06)
    padding_y = int(h * 0.10)
    x1 = max(0, x - padding_x)
    y1 = max(0, y - padding_y)
    x2 = min(width, x + w + padding_x)
    y2 = min(height, y + h + padding_y)

    logger.info("Label crop detected: x=%s y=%s w=%s h=%s", x1, y1, x2 - x1, y2 - y1)
    return rgb_image[y1:y2, x1:x2]


def preprocess_for_ocr(rgb_image: object) -> list[object]:
    import cv2

    gray = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape[:2]
    scale = max(1.0, 1600 / max(width, height))
    if scale > 1:
        gray = cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )

    denoised = cv2.fastNlMeansDenoising(gray, h=10)
    sharpened = sharpen(denoised)
    contrast = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(sharpened)
    threshold = cv2.adaptiveThreshold(
        contrast,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        9,
    )

    return [contrast, threshold]


def sharpen(gray_image: object) -> object:
    import cv2
    import numpy as np

    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    return cv2.filter2D(gray_image, -1, kernel)
