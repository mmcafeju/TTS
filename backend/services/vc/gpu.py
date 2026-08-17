"""GPU / VRAM helpers for the voice-conversion engine.

The RVC engine runs in its own subprocess, so VRAM checks here are
best-effort guards: before enqueuing training/convert jobs we verify the
dedicated venv's torch reports a usable CUDA device and enough free VRAM.
RVC needs the generated model + feature tensors to fit alongside the
HuBERT embedder and the generator/discriminator during training.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Minimum free VRAM (bytes) we require before starting a training job.
# RTX 4070 (16GB) comfortably exceeds this; the 8GB-class GPUs the feature
# targets (batch size 4, 40k SR, no GPU dataset caching) fit within ~6.5GB.
MIN_TRAIN_VRAM = 6 * 1024**3
MIN_CONVERT_VRAM = 2 * 1024**3

# Extra pad we subtract from the reported total before computing "free"
# (the OS + display + other apps already hold part of the VRAM).
_OS_RESERVE = 512 * 1024**2


def get_rvc_python() -> Path:
    """Path to the Python interpreter for the dedicated RVC venv.

    Resolution order:
      1. ``VOICEBOX_RVC_PYTHON`` environment variable (absolute path).
      2. A venv bundled next to the engine: ``backend/rvc_engine/.venv``.
      3. ``sys.executable`` (the current interpreter) as a fallback.

    Returns:
        Path: Absolute path to the python executable.
    """
    from ...config import get_rvc_engine_dir

    import os as _os

    if _os.environ.get("VOICEBOX_RVC_PYTHON"):
        return Path(_os.environ["VOICEBOX_RVC_PYTHON"]).resolve()

    venv_dir = get_rvc_engine_dir() / ".venv"
    if sys.platform == "win32":
        candidate = venv_dir / "Scripts" / "python.exe"
    else:
        candidate = venv_dir / "bin" / "python"
    if candidate.exists():
        return candidate.resolve()

    return Path(sys.executable)


def _probe_gpu() -> dict | None:
    """Ask the RVC venv's torch for CUDA device info. Returns None on any failure."""
    code = (
        "import json, torch\n"
        "if not torch.cuda.is_available():\n"
        "    print(json.dumps({'available': False})); raise SystemExit(0)\n"
        "p = torch.cuda.get_device_properties(0)\n"
        "import torch\n"
        "free, _total = torch.cuda.mem_get_info(0)\n"
        "print(json.dumps({\n"
        "  'available': True,\n"
        "  'name': torch.cuda.get_device_name(0),\n"
        "  'total_vram': p.total_memory,\n"
        "  'free_vram': free,\n"
        "}))\n"
    )
    try:
        result = subprocess.run(
            [str(get_rvc_python()), "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("VC GPU probe failed: %s", e)
        return None
    try:
        payload = result.stdout.strip().splitlines()[-1]
        return json.loads(payload)
    except (ValueError, IndexError, json.JSONDecodeError):
        logger.warning("VC GPU probe returned unparsable output: %s", result.stdout.strip())
        return None


def get_vc_gpu_status() -> dict:
    """Public status payload for /api/vc/status."""
    info = _probe_gpu()
    if info is None:
        return {
            "available": False,
            "engine_ready": False,
            "reason": "RVC venv could not be probed (is it installed?)",
        }
    if not info.get("available"):
        return {"available": False, "engine_ready": False, "reason": "No CUDA device in RVC venv"}
    free = info.get("free_vram", 0)
    total = info.get("total_vram", 0)
    can_train = free - _OS_RESERVE >= MIN_TRAIN_VRAM
    can_convert = free - _OS_RESERVE >= MIN_CONVERT_VRAM
    return {
        "available": True,
        "engine_ready": True,
        "device_name": info.get("name"),
        "total_vram": total,
        "free_vram": free,
        "can_train": can_train,
        "can_convert": can_convert,
    }


def require_engine_ready() -> None:
    """Raise a RuntimeError with a friendly message when RVC can't run."""
    status = get_vc_gpu_status()
    if not status.get("engine_ready"):
        raise RuntimeError(status.get("reason", "RVC engine unavailable"))
