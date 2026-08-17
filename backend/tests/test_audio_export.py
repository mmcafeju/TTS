"""Unit tests for audio_export.py: encode a synthetic mono clip to all formats.

Run: python -m pytest backend/tests/test_audio_export.py -q
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from backend.utils.audio_export import export_audio_file, resolve_ffmpeg, get_format_spec

_FFMPEG = None
_NULL = None


def _setup_module_state():
    global _FFMPEG, _NULL
    _FFMPEG = resolve_ffmpeg()
    _NULL = "NUL" if os.name == "nt" else "/dev/null"


def _make_speech_like(sr=24000, dur=10.0):
    out = np.zeros(int(sr * dur))
    t_global = 0
    while t_global < out.size:
        r = np.random.default_rng(t_global)
        slen = int(sr * r.uniform(0.25, 0.9))
        pause = int(sr * r.uniform(0.15, 0.6))
        if slen > out.size - t_global:
            slen = out.size - t_global
        if slen < sr * 0.1:
            break
        tt = np.arange(slen) / sr
        f0 = r.uniform(110, 180)
        syl = r.uniform(2.5, 4.5)
        amp = r.uniform(0.4, 0.9)
        x = amp * np.sin(
            2 * np.pi * f0 * tt
            + 0.8 * np.sin(2 * np.pi * 3 * tt)
            + 0.3 * np.sin(2 * np.pi * 6 * tt)
        )
        x *= np.clip(np.sin(2 * np.pi * syl * tt), 0, 1) ** 0.3
        out[t_global : t_global + slen] += x
        t_global += slen + pause
    out /= np.abs(out).max()
    return out.astype(np.float32)


def _ebur128(path):
    r = subprocess.run(
        [
            _FFMPEG,
            "-nostdin",
            "-hide_banner",
            "-i",
            str(path),
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            _NULL,
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr[-800:]
    tail = r.stderr.split("Summary:")[-1]
    i = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", tail)[0])
    tp = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", tail)[0])
    return i, tp


def _setup_tmp():
    _setup_module_state()
    audio = _make_speech_like()
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "sample.wav"
    sf.write(str(src), audio, 24000, format="WAV", subtype="FLOAT")
    quiet = tmp / "quiet.wav"
    sf.write(
        str(quiet),
        (audio * 10 ** (-12 / 20)).astype(np.float32),
        24000,
        format="WAV",
        subtype="FLOAT",
    )
    return tmp, src, quiet


def test_encodes_formats_with_correct_specs():
    tmp, src, quiet = _setup_tmp()
    for fmt in ("broadcast", "cd", "mp3"):
        spec = get_format_spec(fmt)
        out = export_audio_file(src, fmt)
        info = sf.info(str(out))
        assert info.channels == 2, "must be dual mono"
        assert info.samplerate == spec["sample_rate"], "sample rate mismatch"
        if fmt == "cd":
            assert info.subtype == "PCM_16"
        elif fmt == "broadcast":
            assert info.subtype == "PCM_24"
        else:
            assert out.suffix == ".mp3"


def test_loudness_targets_broadcast_and_mp3():
    tmp, src, quiet = _setup_tmp()
    for fmt, target in (("broadcast", -24.0), ("mp3", -14.0)):
        for name, path in (("loud", src), ("quiet", quiet)):
            out = export_audio_file(path, fmt)
            i, tp = _ebur128(out)
            assert abs(i - target) <= 1.0, f"{fmt}/{name} off by {abs(i - target):.2f} LU"
            assert tp <= -1.0, f"{fmt}/{name} true peak too hot: {tp} dBTP"


def test_limiter_keeps_true_peak_in_spec():
    _setup_module_state()
    sr = 24000
    dur = 12.0
    n = int(sr * dur)
    base = np.zeros(n)
    t = 0
    while t < n:
        r = np.random.default_rng(t)
        slen = int(sr * r.uniform(0.3, 0.7))
        pause = int(sr * r.uniform(0.2, 0.5))
        seg = n - t
        if slen > seg:
            slen = seg
        tt = np.arange(slen) / sr
        x = (
            0.6
            * np.sin(2 * np.pi * r.uniform(110, 170) * tt + 0.6 * np.sin(2 * np.pi * 3 * tt))
            * np.clip(np.sin(2 * np.pi * 4 * tt), 0, 1) ** 0.5
        )
        base[t : t + slen] = x
        t += slen + pause
    base /= np.abs(base).max()
    sig = base * 10 ** (-12 / 20)
    for i in range(int(sr), n, int(sr * 0.7)):
        sig[i : i + 8] = 1.0
    sig = np.clip(sig, -1, 1).astype(np.float32)

    tmp = Path(tempfile.mkdtemp())
    src = tmp / "clicks.wav"
    sf.write(str(src), sig, sr, format="WAV", subtype="FLOAT")
    input_i, input_tp = _ebur128(src)
    assert input_tp - input_i > 16.0, "test precondition: needs a limiter case"

    for fmt, target in (("broadcast", -24.0), ("mp3", -14.0)):
        out = export_audio_file(src, fmt)
        i, tp = _ebur128(out)
        assert abs(i - target) <= 1.0
        assert tp <= -1.0, f"{fmt} true peak too hot: {tp} dBTP"


def test_broadcast_reencedes_in_place():
    tmp, src, quiet = _setup_tmp()
    out = export_audio_file(src, "broadcast")
    assert out.resolve() == src.resolve()
