from __future__ import annotations

from dataclasses import dataclass
import asyncio
import logging
from pathlib import Path
import re
import subprocess
import threading

from services.ocr_service import extract_model_candidates
from utils.normalize import normalize_model


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceResult:
    text: str
    candidates: list[str]


class VoiceService:
    def __init__(self, model_name: str = "base") -> None:
        self.model_name = model_name
        self._model = None
        self._model_lock = threading.Lock()

    async def recognize_models(self, audio_path: Path) -> VoiceResult:
        logger.info("Voice recognition started for audio: %s", audio_path)
        normalized_audio_path = await asyncio.to_thread(normalize_audio, audio_path)
        text = await asyncio.to_thread(self._transcribe_sync, normalized_audio_path)
        processed_text = postprocess_voice_text(text)
        candidates = extract_voice_model_candidates(processed_text)
        logger.info(
            "Voice recognition completed: candidates=%s text=%r processed=%r",
            candidates,
            text,
            processed_text,
        )
        return VoiceResult(text=processed_text or text, candidates=candidates)

    def _transcribe_sync(self, audio_path: Path) -> str:
        model = self._get_model()
        result = model.transcribe(
            str(audio_path),
            fp16=False,
            language="en",
            task="transcribe",
        )
        return str(result.get("text", "")).strip()

    def _get_model(self):
        if self._model is not None:
            return self._model

        try:
            import whisper
        except ImportError as exc:
            logger.exception("openai-whisper is not installed")
            raise RuntimeError("openai-whisper is not installed") from exc

        with self._model_lock:
            if self._model is None:
                logger.info("Loading Whisper model: %s", self.model_name)
                self._model = whisper.load_model(self.model_name)

        return self._model


def normalize_audio(audio_path: Path) -> Path:
    output_path = audio_path.with_suffix(".wav")
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-af",
        "loudnorm",
        str(output_path),
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("ffmpeg audio normalization failed: %s", result.stderr)
        raise RuntimeError("ffmpeg failed to normalize voice message")

    return output_path


NUMBER_WORDS = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "to": "2",
    "too": "2",
    "three": "3",
    "four": "4",
    "for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "ate": "8",
    "nine": "9",
}


def postprocess_voice_text(text: str) -> str:
    if not text:
        return ""

    normalized = text.lower()
    normalized = re.sub(r"(?<=\d)[.,\s]+(?=\d)", "", normalized)
    normalized = replace_spoken_digit_sequences(normalized)
    normalized = normalized.upper()
    normalized = re.sub(r"[,.;:]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def replace_spoken_digit_sequences(text: str) -> str:
    words_pattern = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))

    def replace_match(match: re.Match[str]) -> str:
        words = re.findall(words_pattern, match.group(0), flags=re.IGNORECASE)
        return "".join(NUMBER_WORDS[word.lower()] for word in words)

    return re.sub(
        rf"\b(?:{words_pattern})(?:[\s-]+(?:{words_pattern}))+\b",
        replace_match,
        text,
        flags=re.IGNORECASE,
    )


def extract_voice_model_candidates(text: str) -> list[str]:
    candidates = extract_model_candidates(text)
    compact = normalize_model(text)

    for match in re.finditer(r"\d{4,6}", compact):
        digits = match.group(0)
        candidates.append(f"{digits}NI")
        candidates.append(digits)

    for match in re.finditer(r"\d{3,6}[A-Z]{1,6}", compact):
        candidates.append(match.group(0))

    for match in re.finditer(r"(?:DS|DHI|DH|IPC|NVR|XVR|HAC)[A-Z0-9]{4,30}", compact):
        candidates.append(match.group(0))

    return list(dict.fromkeys(candidates))
