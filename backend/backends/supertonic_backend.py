"""
Supertonic 3 TTS backend implementation.

Wraps the official ``supertonic`` PyPI SDK (ONNX Runtime, CPU-only) for
preset-speaker TTS. 99M parameters, 44.1kHz output, 31 languages.

Supertonic ships 10 pre-built voice styles (F1–F5 female, M1–M5 male) as
``voice_styles/*.json`` in the model repo. There is no zero-shot voice
cloning — the engine is preset-only, so voice prompts are stored as
deferred ``{"voice_type": "preset", "preset_voice_id": "M1"}`` dicts built
by the profile service.

Key properties (from the Phase 0 dependency audit):
  - Sample rate: 44100 Hz
  - Providers: CPUExecutionProvider only (upstream has no GPU path)
  - Deterministic: seeding ``numpy`` reproduces output exactly
  - Download: huggingface_hub snapshot_download, no token required
  - No torch / no inspect.getsource / no importlib.metadata usage

Languages supported (31): en, ko, ja, ar, bg, cs, da, de, el, es, et, fi,
fr, hi, hr, hu, id, it, lt, lv, nl, pl, pt, ro, ru, sk, sl, sv, tr, uk, vi.
Voicebox codes outside this set (zh, he, ms, no, sw) map to the model's
``<na>`` language-agnostic fallback token.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from . import TTSBackend
from .base import model_load_progress

logger = logging.getLogger(__name__)

# ── Model metadata ──────────────────────────────────────────────────

SUPERTONIC_HF_REPO = "Supertone/supertonic-3"
SUPERTONIC_HF_REVISION = "724fb5abbf5502583fb520898d45929e62f02c0b"
SUPERTONIC_SAMPLE_RATE = 44100

# Default voice if none specified
SUPERTONIC_DEFAULT_VOICE = "M1"

# All available Supertonic voices: (voice_id, display_name, gender, lang_code)
# The same 10 voice styles work for every supported language; "en" is used
# as the representative language for the profile form's auto-set behavior.
SUPERTONIC_VOICES = [
    ("F1", "F1", "female", "en"),
    ("F2", "F2", "female", "en"),
    ("F3", "F3", "female", "en"),
    ("F4", "F4", "female", "en"),
    ("F5", "F5", "female", "en"),
    ("M1", "M1", "male", "en"),
    ("M2", "M2", "male", "en"),
    ("M3", "M3", "male", "en"),
    ("M4", "M4", "male", "en"),
    ("M5", "M5", "male", "en"),
]

# Language codes the model understands natively.
SUPERTONIC_LANGUAGES = {
    "en", "ko", "ja", "ar", "bg", "cs", "da", "de", "el", "es",
    "et", "fi", "fr", "hi", "hr", "hu", "id", "it", "lt", "lv",
    "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "tr", "uk", "vi",
}

# Model files required for the engine to be considered cached.
REQUIRED_MODEL_FILES = [
    "onnx/duration_predictor.onnx",
    "onnx/text_encoder.onnx",
    "onnx/vector_estimator.onnx",
    "onnx/vocoder.onnx",
    "onnx/tts.json",
    "onnx/unicode_indexer.json",
]

# Only fetch the files the engine actually needs (~400 MB, skips the
# demo audio samples, README and hero image that live in the repo).
DOWNLOAD_ALLOW_PATTERNS = [
    "onnx/*",
    "voice_styles/*",
    "config.json",
]


class SupertonicBackend:
    """Supertonic 3 TTS backend — 10 preset voices, 31 languages, CPU-only."""

    def __init__(self):
        self._tts = None
        self.model_size = "default"
        self._model_dir: Optional[Path] = None

    def _get_model_dir(self) -> Path:
        if self._model_dir is None:
            from ..config import get_models_dir

            self._model_dir = get_models_dir() / "supertonic-3"
        return self._model_dir

    def is_loaded(self) -> bool:
        return self._tts is not None

    def _get_model_path(self, model_size: str) -> str:
        return SUPERTONIC_HF_REPO

    def _is_model_cached(self, model_size: str = "default") -> bool:
        """Check whether the Supertonic model files exist on disk."""
        model_dir = self._get_model_dir()

        if not model_dir.exists():
            return False

        # A snapshot_download still in flight leaves .incomplete blobs.
        if any(model_dir.rglob("*.incomplete")):
            return False

        return all((model_dir / rel).exists() for rel in REQUIRED_MODEL_FILES)

    async def load_model(self, model_size: str = "default") -> None:
        """Load the Supertonic model, downloading it first if needed."""
        if self._tts is not None:
            return
        await asyncio.to_thread(self._load_model_sync)

    def _load_model_sync(self) -> None:
        """Synchronous model loading + download."""
        model_name = "supertonic-3"
        is_cached = self._is_model_cached()
        model_dir = self._get_model_dir()

        with model_load_progress(model_name, is_cached):
            if not is_cached:
                logger.info(
                    "Downloading Supertonic 3 model to %s...", model_dir
                )
                self._download_model(model_dir)

            from supertonic import TTS

            logger.info("Loading Supertonic 3 on CPU...")
            self._tts = TTS(model_dir=str(model_dir), auto_download=False)

        logger.info("Supertonic 3 loaded successfully")

    def _download_model(self, model_dir: Path) -> None:
        """Download the Supertonic model files from HuggingFace."""
        from huggingface_hub import snapshot_download

        model_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=SUPERTONIC_HF_REPO,
            revision=SUPERTONIC_HF_REVISION,
            local_dir=str(model_dir),
            allow_patterns=DOWNLOAD_ALLOW_PATTERNS,
        )

    def unload_model(self) -> None:
        """Unload model to free memory."""
        if self._tts is not None:
            del self._tts
            self._tts = None
            logger.info("Supertonic unloaded")

    async def create_voice_prompt(
        self,
        audio_path: str,
        reference_text: str,
        use_cache: bool = True,
    ) -> tuple[dict, bool]:
        """
        Create voice prompt for Supertonic.

        Supertonic doesn't do zero-shot cloning from arbitrary audio. When
        called for a cloned profile (fallback), uses the default voice. For
        preset profiles, the voice_prompt dict is built by the profile
        service and bypasses this method entirely.
        """
        return {
            "voice_type": "preset",
            "preset_engine": "supertonic",
            "preset_voice_id": SUPERTONIC_DEFAULT_VOICE,
        }, False

    async def combine_voice_prompts(
        self,
        audio_paths: list[str],
        reference_texts: list[str],
    ) -> tuple[np.ndarray, str]:
        """Combine voice prompts — not used for preset-only engines."""
        return np.zeros(0, dtype=np.float32), " ".join(reference_texts)

    def _resolve_language(self, language: str) -> str:
        """Map a Voicebox language code to a Supertonic code (or ``na``)."""
        if language in SUPERTONIC_LANGUAGES:
            return language
        return "na"

    async def generate(
        self,
        text: str,
        voice_prompt: dict,
        language: str = "en",
        seed: Optional[int] = None,
        instruct: Optional[str] = None,
    ) -> tuple[np.ndarray, int]:
        """
        Generate audio from text using Supertonic.

        Args:
            text: Text to synthesize
            voice_prompt: Dict with preset_voice_id key (F1–F5 / M1–M5)
            language: Language code (31 supported; unknown maps to ``na``)
            seed: Random seed for reproducibility (Supertonic is
                  deterministic when numpy is seeded)
            instruct: Not supported by Supertonic (ignored)

        Returns:
            Tuple of (audio_array, sample_rate)
        """
        await self.load_model()

        voice_name = (
            voice_prompt.get("preset_voice_id") or voice_prompt.get("supertonic_voice")
            or SUPERTONIC_DEFAULT_VOICE
        )
        lang = self._resolve_language(language)

        def _generate_sync():
            if seed is not None:
                np.random.seed(seed)

            style = self._tts.get_voice_style(voice_name)
            wav, _dur = self._tts.synthesize(
                text,
                voice_style=style,
                lang=lang,
            )
            return wav[0].astype(np.float32), SUPERTONIC_SAMPLE_RATE

        return await asyncio.to_thread(_generate_sync)
