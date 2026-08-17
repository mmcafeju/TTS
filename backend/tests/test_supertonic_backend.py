"""Supertonic 3 backend unit tests.

Covers engine registration, preset voice metadata, language resolution,
and cache detection. Model download/load is exercised by the e2e model
test (test_all_models_e2e.py) since it needs the real weights.
"""

import pytest

from backend.backends import (
    get_all_model_configs,
    get_model_config,
    get_tts_backend_for_engine,
)
from backend.backends.supertonic_backend import (
    SUPERTONIC_VOICES,
    SUPERTONIC_LANGUAGES,
    SUPERTONIC_DEFAULT_VOICE,
)


def test_supertonic_model_config_registered():
    cfg = get_model_config("supertonic-3")
    assert cfg is not None
    assert cfg.engine == "supertonic"
    assert cfg.hf_repo_id == "Supertone/supertonic-3"


def test_supertonic_engine_listed():
    from backend.backends import TTS_ENGINES

    assert "supertonic" in TTS_ENGINES


def test_supertonic_backend_factory():
    backend = get_tts_backend_for_engine("supertonic")
    assert backend is not None


def test_supertonic_voices_metadata():
    assert len(SUPERTONIC_VOICES) == 10
    voice_ids = {v[0] for v in SUPERTONIC_VOICES}
    assert voice_ids == {f"F{i}" for i in range(1, 6)} | {f"M{i}" for i in range(1, 6)}
    # Every tuple is (voice_id, name, gender, lang)
    for voice_id, name, gender, lang in SUPERTONIC_VOICES:
        assert voice_id == name
        assert gender in ("male", "female")
        assert lang == "en"
    assert SUPERTONIC_DEFAULT_VOICE in voice_ids


def test_supertonic_language_coverage():
    # Covers all 31 model languages including the new 13 Voicebox codes.
    assert len(SUPERTONIC_LANGUAGES) == 31
    for code in (
        "ar", "bg", "cs", "da", "de", "el", "en", "es", "et", "fi",
        "fr", "hi", "hr", "hu", "id", "it", "ja", "ko", "lt", "lv",
        "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "tr", "uk", "vi",
    ):
        assert code in SUPERTONIC_LANGUAGES


def test_language_resolution_maps_unsupported_to_na():
    backend = get_tts_backend_for_engine("supertonic")
    assert backend._resolve_language("en") == "en"
    assert backend._resolve_language("ko") == "ko"
    # Voicebox codes the model doesn't support map to the "na" fallback.
    for code in ("zh", "he", "ms", "no", "sw"):
        assert backend._resolve_language(code) == "na"


def test_is_model_cached_false_when_missing(tmp_path, monkeypatch):
    backend = get_tts_backend_for_engine("supertonic")
    monkeypatch.setattr(backend, "_model_dir", tmp_path)
    assert not backend._is_model_cached()

    # Partial download (only some files) is not cached.
    (tmp_path / "onnx").mkdir(parents=True)
    (tmp_path / "onnx" / "vocoder.onnx").write_bytes(b"x")
    assert not backend._is_model_cached()


def test_is_model_cached_true_with_all_files(tmp_path, monkeypatch):
    backend = get_tts_backend_for_engine("supertonic")
    monkeypatch.setattr(backend, "_model_dir", tmp_path)

    files = [
        "onnx/duration_predictor.onnx",
        "onnx/text_encoder.onnx",
        "onnx/vector_estimator.onnx",
        "onnx/vocoder.onnx",
        "onnx/tts.json",
        "onnx/unicode_indexer.json",
    ]
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")

    assert backend._is_model_cached()


def test_is_model_cached_false_with_incomplete_blob(tmp_path, monkeypatch):
    backend = get_tts_backend_for_engine("supertonic")
    monkeypatch.setattr(backend, "_model_dir", tmp_path)

    for rel in (
        "onnx/duration_predictor.onnx",
        "onnx/text_encoder.onnx",
        "onnx/vector_estimator.onnx",
        "onnx/vocoder.onnx",
        "onnx/tts.json",
        "onnx/unicode_indexer.json",
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")

    # An in-flight download leaves .incomplete blobs -> not cached.
    (tmp_path / "onnx" / "vocoder.onnx.incomplete").write_bytes(b"partial")
    assert not backend._is_model_cached()
