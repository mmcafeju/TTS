"""Unit tests for segment-splice logic in services.chunks / utils.chunked_tts.

Run: python -m pytest backend/tests/test_chunk_splice.py -q
"""
import numpy as np

from backend.utils.chunked_tts import (
    chunk_meta_from_audio,
    compute_chunk_boundaries,
    concatenate_audio_chunks,
    split_text_into_chunks,
)
from backend.services.chunks import splice_chunk_into_audio

SR = 24000


def _gen_chunks(n=4, dur_ms=1000):
    return [np.full(SR * dur_ms // 1000, float(i + 1), dtype=np.float32) for i in range(n)]


def _meta(chunks, texts):
    return chunk_meta_from_audio(texts, chunks, SR, 50)


def test_split_meta_matches_concat():
    texts = ["First sentence.", "Second sentence.", "Third sentence.", "Fourth sentence."]
    chunks = _gen_chunks(len(texts))
    full = concatenate_audio_chunks(chunks, SR, 50)
    meta = _meta(chunks, texts)
    # Boundaries are monotonically increasing and stay within the total
    prev_end = 0
    for m in meta:
        assert m["start_ms"] <= m["end_ms"]
        assert m["start_ms"] >= prev_end - 60  # crossfade overlap tolerance
        prev_end = m["end_ms"]
    assert abs(meta[-1]["end_ms"] - len(full) * 1000 / SR) < 60


def _interior(audio, start_ms, end_ms, frac=0.8):
    """Slice the middle ``frac`` of a window (skips the fade edges)."""
    s = int(start_ms * SR // 1000)
    e = int(end_ms * SR // 1000)
    margin = int((e - s) * (1 - frac) / 2)
    return audio[s + margin : e - margin]


def test_splice_same_length_preserves_total():
    texts = ["A.", "B.", "C.", "D."]
    chunks = _gen_chunks(len(texts))
    full = concatenate_audio_chunks(chunks, SR, 50)
    meta = _meta(chunks, texts)
    new_chunk = np.full(SR, 99.0, dtype=np.float32)  # 1s, same as originals
    spliced, new_meta = splice_chunk_into_audio(full, SR, meta, 1, new_chunk, 50)
    fade = SR * 50 // 1000
    orig_len = meta[1]["duration_ms"] * SR // 1000
    expected = len(full) - 2 * fade + (len(new_chunk) - orig_len)
    assert abs(len(spliced) - expected) <= 2
    assert len(new_meta) == 4
    # Chunk 1 replaced with 99s (interior, past the fade edges)
    assert np.allclose(_interior(spliced, new_meta[1]["start_ms"], new_meta[1]["end_ms"]), 99.0)


def test_splice_different_length_reflows_downstream():
    texts = ["A.", "B.", "C.", "D."]
    chunks = _gen_chunks(len(texts), dur_ms=800)
    full = concatenate_audio_chunks(chunks, SR, 50)
    meta = _meta(chunks, texts)
    long_chunk = np.full(2 * SR, 55.0, dtype=np.float32)  # 2s instead of 0.8s
    spliced, new_meta = splice_chunk_into_audio(full, SR, meta, 2, long_chunk, 50)
    delta_ms = 2000 - 800
    # Chunks after idx 2 shifted by +delta_ms
    assert new_meta[3]["start_ms"] == meta[3]["start_ms"] + delta_ms
    assert new_meta[3]["end_ms"] == meta[3]["end_ms"] + delta_ms
    # Total = full - 2*fade + (new chunk length - original chunk length)
    fade = SR * 50 // 1000
    orig_len = meta[2]["duration_ms"] * SR // 1000
    expected = len(full) - 2 * fade + (len(long_chunk) - orig_len)
    assert abs(len(spliced) - expected) <= 2
    # Chunk 2 itself is now the long chunk (interior)
    assert np.allclose(_interior(spliced, new_meta[2]["start_ms"], new_meta[2]["end_ms"]), 55.0)


def test_splice_into_flat_single_chunk():
    # Legacy single-shot generation has a single chunk spanning the file.
    full = np.full(SR * 2, 1.0, dtype=np.float32)
    meta = [{"index": 0, "text": "hi.", "start_ms": 0, "end_ms": 2000, "duration_ms": 2000}]
    new_chunk = np.full(SR, 2.0, dtype=np.float32)
    spliced, new_meta = splice_chunk_into_audio(full, SR, meta, 0, new_chunk, 50)
    assert abs(len(spliced) - SR) <= 2 * SR * 50 // 1000
    assert new_meta[0]["duration_ms"] == 1000


def test_text_override_rejects_missing():
    # splice_chunk_into_audio requires an in-range index
    full = np.full(SR, 1.0, dtype=np.float32)
    meta = [{"index": 0, "text": "x", "start_ms": 0, "end_ms": 1000, "duration_ms": 1000}]
    try:
        splice_chunk_into_audio(full, SR, meta, 3, np.full(SR, 2.0), 50)
        assert False, "expected IndexError"
    except IndexError:
        pass