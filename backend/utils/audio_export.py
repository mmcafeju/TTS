"""
Export TTS output to delivery formats (broadcast / CD / mp3).

Each format is produced right after the engine output and before the final
save, using the bundled ffmpeg. The output is always dual-mono (mono signal
duplicated to both channels) so it plays identically on mono and stereo
playback systems.

  broadcast : 48 kHz / 24-bit PCM WAV, -24 LUFS, true peak <= -1.0 dBTP, dual mono
  cd        : 44.1 kHz / 16-bit PCM WAV (1,411.2 kbps), dual mono
  mp3       : 44.1 kHz / 192 kbps CBR MP3, -14 LUFS, dual mono

Formats with an integrated-loudness target (broadcast, mp3) use ffmpeg's
``loudnorm`` filter in two-pass linear mode: the first pass measures the
source loudness, the second applies a pure linear gain (plus true-peak
limiting) so speech lands on the target without dynamic compression.

ffmpeg resolution order: ``VOICEBOX_FFMPEG`` env var -> the RVC engine's
bundled ``bin/ffmpeg`` (shares ``config.get_rvc_engine_dir`` resolution so it
keeps working in PyInstaller frozen builds) -> ``ffmpeg`` on PATH.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from .. import config

logger = logging.getLogger(__name__)

#: EBU R128 meters measure dual-mono (identical L/R) stereo 3.01 LU hotter than
#: the same signal in mono, because the BS.1770 stereo downmix is
#: (L + R) / sqrt(2). Every delivery format here is dual-mono, so the
#: loudness-normalization target is shifted down by this amount: the mono
#: signal is normalized to ``target - DUAL_MONO_OFFSET`` and the final
#: dual-mono file then measures ``target`` on a standard meter.
DUAL_MONO_OFFSET_DB = 10.0 * 0.3010299956639812  # 10 * log10(2) == 3.010299957

# ---------------------------------------------------------------------------
# Format specifications
# ---------------------------------------------------------------------------

#: Delivery format -> encoding spec. ``target_lufs``/``true_peak_db`` being
#: None means "no loudness normalization" (CD audio has no loudness target).
FORMAT_SPECS: dict[str, dict] = {
    "broadcast": {
        "sample_rate": 48000,
        "codec": "pcm_s24le",
        "container": "wav",
        "extension": ".wav",
        "target_lufs": -24.0,
        "true_peak_db": -1.0,
        "bitrate": None,
    },
    "cd": {
        "sample_rate": 44100,
        "codec": "pcm_s16le",
        "container": "wav",
        "extension": ".wav",
        "target_lufs": None,
        "true_peak_db": None,
        "bitrate": None,
    },
    "mp3": {
        "sample_rate": 44100,
        "codec": "libmp3lame",
        "container": "mp3",
        "extension": ".mp3",
        "target_lufs": -14.0,
        "true_peak_db": -1.0,
        "bitrate": "192k",
    },
}


def get_format_spec(output_format: str) -> dict:
    """Return the spec dict for a delivery format, raising on unknown names."""
    try:
        return FORMAT_SPECS[output_format]
    except KeyError:
        raise ValueError(f"Unsupported output format: {output_format}") from None


# ---------------------------------------------------------------------------
# ffmpeg resolution
# ---------------------------------------------------------------------------

def _null_device() -> str:
    return "NUL" if os.name == "nt" else "/dev/null"


def resolve_ffmpeg() -> str:
    """Locate the ffmpeg executable.

    Search order: ``VOICEBOX_FFMPEG`` env var -> the RVC engine's bundled
    ``bin/ffmpeg(.exe)`` -> ``ffmpeg`` on PATH.
    """
    candidates: list[str] = []

    env = os.environ.get("VOICEBOX_FFMPEG")
    if env:
        candidates.append(env)

    bundled = config.get_rvc_engine_dir() / "bin"
    for name in ("ffmpeg.exe", "ffmpeg"):
        candidate = bundled / name
        if candidate.is_file():
            candidates.append(str(candidate))
            break

    which = shutil.which("ffmpeg")
    if which:
        candidates.append(which)

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    raise RuntimeError(
        "ffmpeg not found. Set VOICEBOX_FFMPEG, install ffmpeg, or ensure the "
        "RVC engine's bundled bin/ is present."
    )


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def _loudnorm_target(spec: dict) -> float:
    """Effective loudnorm target, compensated for dual-mono measurement.

    See the DUAL_MONO_OFFSET_DB note: normalizing the mono signal to
    ``target - 3.01`` makes the final dual-mono file measure ``target``.
    """
    return float(spec["target_lufs"]) - DUAL_MONO_OFFSET_DB


def _measure_loudness(ffmpeg: str, src: Path, spec: dict) -> dict:
    """Run a loudnorm measurement pass and return parsed JSON parameters."""
    af = (
        f"loudnorm=I={_loudnorm_target(spec):.3f}:TP={spec['true_peak_db']}:LRA=11:"
        "print_format=json"
    )
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-i",
        str(src),
        "-af",
        af,
        "-f",
        "null",
        _null_device(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg loudness measurement failed for {src.name}: {proc.stderr[-500:]}"
        )
    try:
        match = re.search(r"\{.*\}", proc.stderr, re.DOTALL)
        if not match:
            raise ValueError("no JSON block in loudnorm output")
        data = json.loads(match.group(0))
        return {
            "input_i": data["input_i"],
            "input_tp": data["input_tp"],
            "input_lra": data["input_lra"],
            "input_thresh": data["input_thresh"],
            "offset": data["target_offset"],
        }
    except Exception as exc:  # noqa: BLE001 - fall back to dynamic mode
        logger.warning(
            "could not parse loudnorm measurement, using dynamic mode: %s", exc
        )
        return {}


def _loudnorm_filter(spec: dict, measured: dict) -> str:
    """Build the loudnorm filter string (linear two-pass or dynamic single-pass)."""
    af = f"loudnorm=I={_loudnorm_target(spec):.3f}:TP={spec['true_peak_db']}:LRA=11"
    if measured:
        af += (
            ":linear=true"
            f":measured_I={measured['input_i']}"
            f":measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}"
            f":measured_thresh={measured['input_thresh']}"
            f":offset={measured['offset']}"
        )
    return af


def _encode(ffmpeg: str, src: Path, spec: dict, out_path: Path, measured: dict) -> None:
    """Run the ffmpeg encode pass for a format spec.

    ffmpeg refuses to edit files in place (e.g. WAV -> WAV re-encode), so the
    output is always written to a temp sibling and atomically moved into place.
    """
    filters = ["aformat=channel_layouts=mono"]
    if spec["target_lufs"] is not None:
        filters.append(_loudnorm_filter(spec, measured))
    filters.append("pan=stereo|c0=c0|c1=c0")
    filters.append(f"aresample={spec['sample_rate']}")

    temp_out = out_path.with_name(out_path.name + ".ffmpeg.tmp")
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-y",
        "-i",
        str(src),
        "-af",
        ",".join(filters),
        "-ar",
        str(spec["sample_rate"]),
        "-ac",
        "2",
        "-c:a",
        spec["codec"],
    ]
    if spec["bitrate"]:
        cmd += ["-b:a", spec["bitrate"]]
    cmd += ["-f", spec["container"]]
    cmd.append(str(temp_out))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg encode to {out_path.name} failed: {proc.stderr[-800:]}"
            )
        if not temp_out.is_file() or temp_out.stat().st_size == 0:
            raise RuntimeError(f"ffmpeg produced no output for {out_path.name}")
        temp_out.replace(out_path)
    finally:
        temp_out.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export_audio_file(src_path: str | Path, output_format: str) -> Path:
    """Encode an existing audio file to a delivery format.

    Writes ``<src stem>.<ext>`` next to the source and returns that path. For
    broadcast/CD the output keeps the ``.wav`` extension, so the exported file
    replaces the source in place and the same path is returned.

    Args:
        src_path: Path to the source audio (typically a generated WAV).
        output_format: One of ``broadcast``, ``cd``, ``mp3``.

    Returns:
        Absolute path of the exported file (== src when re-encoded in place).
    """
    src = Path(src_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Source audio not found: {src}")

    spec = get_format_spec(output_format)
    out_path = src.with_suffix(spec["extension"])

    ffmpeg = resolve_ffmpeg()

    measured: dict = {}
    if spec["target_lufs"] is not None:
        measured = _measure_loudness(ffmpeg, src, spec)

    _encode(ffmpeg, src, spec, out_path, measured)

    if spec["codec"] != "libmp3lame":
        import soundfile as sf

        info = sf.info(str(out_path))
        if info.samplerate != spec["sample_rate"] or info.channels != 2:
            logger.warning(
                "export %s unexpected format: %s @ %d Hz, %d ch",
                out_path.name,
                info.format,
                info.samplerate,
                info.channels,
            )

    logger.info(
        "exported %s -> %s (%s)", src.name, out_path.name, output_format
    )
    return out_path
