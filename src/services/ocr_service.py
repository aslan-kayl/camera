from __future__ import annotations

from dataclasses import dataclass
import asyncio
import logging
from pathlib import Path
import re
import threading

from utils.normalize import normalize_model


logger = logging.getLogger(__name__)

MODEL_PREFIX_RE = re.compile(
    r"\b(?:IDS|DS|DHI|DH|IPC|HAC|NVR|XVR)(?:[\s\-/_.]*[A-Z0-9]{1,12}){1,8}\b",
    re.IGNORECASE,
)
MODEL_TOKEN_RE = re.compile(
    r"\b(?=[A-Z0-9\-/_.\s]{6,50}\b)(?=[A-Z0-9\-/_.\s]*[A-Z])(?=[A-Z0-9\-/_.\s]*\d)"
    r"[A-Z0-9][A-Z0-9\-/_.\s]{4,48}[A-Z0-9]\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OCRResult:
    text: str
    candidates: list[str]


class OCRService:
    def __init__(self, languages: list[str] | None = None, gpu: bool = False) -> None:
        self.languages = languages or ["en"]
        self.gpu = gpu
        self._reader = None
        self._reader_lock = threading.Lock()

    async def recognize_models(self, image_path: Path) -> OCRResult:
        logger.info("OCR started for image: %s", image_path)
        text = await asyncio.to_thread(self._recognize_sync, image_path)
        candidates = extract_model_candidates(text)
        logger.info("OCR completed: candidates=%s text_length=%s", candidates, len(text))
        return OCRResult(text=text, candidates=candidates)

    def _recognize_sync(self, image_path: Path) -> str:
        images = preprocess_image(image_path)
        reader = self._get_reader()
        text_parts: list[str] = []

        for image in images:
            result = reader.readtext(
                image,
                detail=0,
                paragraph=False,
                allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_/ .",
            )
            text_parts.extend(str(item) for item in result if str(item).strip())

        return "\n".join(dict.fromkeys(text_parts))

    def _get_reader(self):
        if self._reader is not None:
            return self._reader

        try:
            import easyocr
        except ImportError as exc:
            logger.exception("easyocr is not installed")
            raise RuntimeError("easyocr is not installed") from exc

        with self._reader_lock:
            if self._reader is None:
                logger.info("Initializing EasyOCR reader languages=%s gpu=%s", self.languages, self.gpu)
                self._reader = easyocr.Reader(self.languages, gpu=self.gpu)

        return self._reader


def preprocess_image(image_path: Path) -> list[object]:
    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError as exc:
        logger.exception("OCR image dependencies are not installed")
        raise RuntimeError("opencv-python and Pillow are required for OCR") from exc

    with Image.open(image_path) as source:
        source = ImageOps.exif_transpose(source).convert("RGB")
        image = np.array(source)

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape[:2]
    scale = max(1.0, 1200 / max(width, height))
    if scale > 1:
        gray = cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )

    denoised = cv2.fastNlMeansDenoising(gray, h=10)
    contrast = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(denoised)
    threshold = cv2.adaptiveThreshold(
        contrast,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        9,
    )

    return [contrast, threshold]


def extract_model_candidates(text: str) -> list[str]:
    if not text:
        return []

    normalized_text = normalize_ocr_text(text)
    candidates: list[str] = []

    for pattern in (MODEL_PREFIX_RE, MODEL_TOKEN_RE):
        for match in pattern.finditer(normalized_text):
            candidate = cleanup_candidate(match.group(0))
            normalized_candidate = normalize_model(candidate)
            if 5 <= len(normalized_candidate) <= 40:
                candidates.append(candidate)

    for line in normalized_text.splitlines():
        candidate = cleanup_candidate(line)
        normalized_candidate = normalize_model(candidate)
        if 5 <= len(normalized_candidate) <= 40 and any(char.isdigit() for char in normalized_candidate):
            candidates.append(candidate)

    return list(dict.fromkeys(candidates))


def normalize_ocr_text(text: str) -> str:
    replacements = {
        "—": "-",
        "–": "-",
        "‐": "-",
        "|": "I",
        "；": ";",
        "：": ":",
    }
    normalized = text.upper()
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)

    normalized = re.sub(r"[^\w\s\-/.]", " ", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    return normalized


def cleanup_candidate(value: str) -> str:
    value = re.sub(r"^(?:MODEL|MOD|МОДЕЛЬ|МОД)\s*[:\-]?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(?:SN|S/N|SERIAL|SERIAL|СЕРИЙНЫЙ)\b.*$", "", value, flags=re.IGNORECASE)
    candidate = value.strip(" .:/_")
    candidate = re.sub(r"\s*[-_/]\s*", "-", candidate)
    candidate = re.sub(r"\s+", "", candidate)
    return candidate.upper()
