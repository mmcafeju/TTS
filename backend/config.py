"""
Configuration module for voicebox backend.

Handles data directory configuration for production bundling.
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Model cache lives inside the app data directory so the whole project is
# self-contained (copyable to another machine without shared folders).
# Override with VOICEBOX_MODELS_DIR to point at an absolute path elsewhere.
# This sets HF_HUB_CACHE so all huggingface_hub downloads go to that path.
_custom_models_dir = os.environ.get("VOICEBOX_MODELS_DIR")
if _custom_models_dir:
    os.environ["HF_HUB_CACHE"] = _custom_models_dir
    logger.info("Model download path set to: %s", _custom_models_dir)
else:
    _default_hf_cache = Path("data").resolve() / "models" / "hf-cache"
    os.environ["HF_HUB_CACHE"] = str(_default_hf_cache)
    logger.info("Model download path set to (default): %s", _default_hf_cache)

# Default data directory (used in development)
_data_dir = Path("data").resolve()


def _path_relative_to_any_data_dir(path: Path) -> Path | None:
    """Extract the path within a data dir from an absolute or relative path."""
    parts = path.parts
    for idx, part in enumerate(parts):
        if part != "data":
            continue

        tail = parts[idx + 1 :]
        if tail:
            return Path(*tail)
        return Path()

    return None


def set_data_dir(path: str | Path):
    """
    Set the data directory path.

    Args:
        path: Path to the data directory
    """
    global _data_dir
    _data_dir = Path(path).resolve()
    _data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Data directory set to: %s", _data_dir)


def get_data_dir() -> Path:
    """
    Get the data directory path.

    Returns:
        Path to the data directory
    """
    return _data_dir


def to_storage_path(path: str | Path) -> str:
    """Convert a filesystem path to a DB-safe path relative to the data dir."""
    resolved_path = Path(path).resolve()

    relative_to_any_data_dir = _path_relative_to_any_data_dir(resolved_path)
    if relative_to_any_data_dir is not None:
        return str(relative_to_any_data_dir)

    try:
        return str(resolved_path.relative_to(_data_dir))
    except ValueError:
        return str(resolved_path)


def resolve_storage_path(path: str | Path | None) -> Path | None:
    """Resolve a DB-stored path against the configured data dir."""
    if path is None:
        return None

    stored_path = Path(path)
    # Empty paths (e.g. failed generations) must not resolve to the data
    # dir itself, which exists and would defeat the callers' 404 guards.
    # Path("") is truthy, so check parts rather than the raw value.
    if not stored_path.parts:
        return None
    if stored_path.is_absolute():
        rebased_path = _path_relative_to_any_data_dir(stored_path)
        if rebased_path is not None:
            candidate = (_data_dir / rebased_path).resolve()
            if candidate.exists() or not stored_path.exists():
                return candidate

        return stored_path

    # 0.3.0 records sometimes stored relative paths with the data-dir name
    # baked in (e.g. "data/profiles/..."). Joining those directly with
    # _data_dir produces a spurious "<data_dir>/data/profiles/..." nest.
    if stored_path.parts and stored_path.parts[0] == "data":
        stored_path = (
            Path(*stored_path.parts[1:]) if len(stored_path.parts) > 1 else Path()
        )

    return (_data_dir / stored_path).resolve()


def get_db_path() -> Path:
    """Get database file path."""
    return _data_dir / "voicebox.db"


def get_profiles_dir() -> Path:
    """Get profiles directory path."""
    path = _data_dir / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_generations_dir() -> Path:
    """Get generations directory path."""
    path = _data_dir / "generations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_captures_dir() -> Path:
    """Get captures directory path."""
    path = _data_dir / "captures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_dir() -> Path:
    """Get cache directory path."""
    path = _data_dir / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_models_dir() -> Path:
    """Get models directory path."""
    path = _data_dir / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_vc_dir() -> Path:
    """Get the voice-conversion (RVC) root directory path."""
    path = _data_dir / "vc"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_vc_uploads_dir() -> Path:
    """Get the voice-conversion upload (dataset/source audio) directory."""
    path = get_vc_dir() / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_vc_models_dir() -> Path:
    """Get the directory holding trained RVC .pth models (one subdir per model)."""
    path = get_vc_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_vc_results_dir() -> Path:
    """Get the directory holding voice-conversion result audio."""
    path = get_vc_dir() / "results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_rvc_engine_dir() -> Path:
    """Locate the vendored RVC engine directory.

    The RVC engine (backend/rvc_engine) is *not* bundled into the PyInstaller
    binary: it carries its own venv + torch and runs as a separate subprocess,
    so it ships as a standalone directory at runtime. Resolution order:

      1. ``VOICEBOX_RVC_DIR`` env var — explicit absolute path to the engine
         root (set by the launcher / user; must be set before server import
         because pipeline.py caches engine-relative paths at module load).
      2. Frozen (PyInstaller): ``rvc_engine`` placed next to the
         ``voicebox-server`` executable (portable layout). Works for both
         ``--onedir`` (dist/<name>/rvc_engine) and ``--onefile`` builds.
      3. Bundled into the PyInstaller archive (``sys._MEIPASS``) — kept as a
         fallback for a future slim engine build that is bundled.
      4. Source checkout: ``backend/rvc_engine`` (development).
    """
    override = os.environ.get("VOICEBOX_RVC_DIR")
    if override:
        return Path(override).resolve()

    if getattr(sys, "frozen", False):
        # Portable layout: engine directory lives beside the server binary.
        exe_dir = Path(sys.executable).resolve().parent
        sibling = exe_dir / "rvc_engine"
        if sibling.is_dir():
            return sibling
        # Fallback: engine was bundled into the one-dir/_MEIPASS payload.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bundled = Path(meipass) / "rvc_engine"
            if bundled.is_dir():
                return bundled
        return sibling

    return Path(__file__).resolve().parent / "rvc_engine"


# Voicebox Cloud (backup & sync). Two hosts: the web app owns auth + device
# pairing (voicebox.sh), the API owns sync + account endpoints
# (api.voicebox.sh). Override both for local development, e.g.
# VOICEBOX_CLOUD_URL=http://localhost:17592 VOICEBOX_CLOUD_API_URL=http://localhost:17593
def get_cloud_web_url() -> str:
    """Base URL of the Voicebox Cloud web app (auth + /connect + exchange)."""
    return os.environ.get("VOICEBOX_CLOUD_URL", "https://voicebox.sh").rstrip("/")


def get_cloud_api_url() -> str:
    """Base URL of the Voicebox Cloud API (bearer-authenticated sync/account)."""
    return os.environ.get("VOICEBOX_CLOUD_API_URL", "https://api.voicebox.sh").rstrip("/")
