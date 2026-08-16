"""Download the RVC engine assets needed for training and inference.

The vendored RVC engine (backend/rvc_engine) expects, relative to its root:

    assets/hubert_base/pytorch_model.bin        — HuBERT embedder (HF transformers)
    assets/hubert_base/config.json              — HuBERT model config
    assets/hubert_base/preprocessor_config.json — HuBERT feature extractor config
    assets/rmvpe/rmvpe.pt                       — RMVPE pitch predictor
    assets/pretrained_v2/f0G40k.pth             — v2 generator pretrain 40k (training)
    assets/pretrained_v2/f0D40k.pth             — v2 discriminator pretrain 40k (training)
    assets/pretrained_v2/f0G48k.pth             — v2 generator pretrain 48k (training)
    assets/pretrained_v2/f0D48k.pth             — v2 discriminator pretrain 48k (training)
    bin/ffmpeg.exe, bin/ffprobe.exe             — audio decoding (infer/audio.py)

These ship in the upstream ``lj1995/VoiceConversionWebUI`` HuggingFace repo.
This script downloads them into the engine's assets directory so the whole
project stays self-contained (no separate model store required).

Usage:
    python -m backend.scripts.download_rvc_assets
"""

import logging
import os
import shutil
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_ID = "lj1995/VoiceConversionWebUI"
REVISION = "main"

# Remote path → local relative path (inside the engine's assets dir).
ASSET_FILES = {
    "hubert_base/pytorch_model.bin": "hubert_base/pytorch_model.bin",
    "hubert_base/config.json": "hubert_base/config.json",
    "hubert_base/preprocessor_config.json": "hubert_base/preprocessor_config.json",
    "rmvpe.pt": "rmvpe/rmvpe.pt",
    "pretrained_v2/f0G40k.pth": "pretrained_v2/f0G40k.pth",
    "pretrained_v2/f0D40k.pth": "pretrained_v2/f0D40k.pth",
    "pretrained_v2/f0G48k.pth": "pretrained_v2/f0G48k.pth",
    "pretrained_v2/f0D48k.pth": "pretrained_v2/f0D48k.pth",
}


def get_engine_assets_dir() -> Path:
    # backend/scripts/download_rvc_assets.py → backend/rvc_engine/assets
    engine_dir = Path(__file__).resolve().parent.parent / "rvc_engine"
    return engine_dir / "assets"


FFMPEG_URL = "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffmpeg-4.4.1-win-64.zip"
FFPROBE_URL = "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffprobe-4.4.1-win-64.zip"


def download_ffmpeg(force: bool = False) -> list[str]:
    """Fetch Windows ffmpeg/ffprobe into the engine's bin/ directory.

    infer/audio.py shells out to ``ffmpeg``/``ffprobe`` for audio decoding, so
    the RVC engine needs them on PATH (the pipeline prepends engine/bin/).
    """
    import io
    import zipfile

    import urllib.request

    engine_dir = Path(__file__).resolve().parent.parent / "rvc_engine"
    bin_dir = engine_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    installed = []
    for name, url in (("ffmpeg.exe", FFMPEG_URL), ("ffprobe.exe", FFPROBE_URL)):
        target = bin_dir / name
        if target.exists() and not force:
            logger.info("Already present: %s", target)
            continue
        logger.info("Downloading %s → %s", url, target)
        with urllib.request.urlopen(url, timeout=180) as resp:
            data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            member = next(m for m in z.namelist() if m.endswith(name))
            target.write_bytes(z.read(member))
        installed.append(str(target))
        logger.info("OK: %s", target)
    return installed



def download_assets(force: bool = False) -> list[str]:
    """Download all RVC engine assets. Returns list of downloaded paths."""
    from huggingface_hub import hf_hub_download

    assets_dir = get_engine_assets_dir()
    downloaded = []
    for remote_path, local_rel in ASSET_FILES.items():
        local_path = assets_dir / local_rel
        if local_path.exists() and not force:
            logger.info("Already present: %s", local_path)
            continue
        logger.info("Downloading %s/%s → %s", REPO_ID, remote_path, local_path)
        # hf_hub_download places the file at local_dir/remote_path, so the
        # remote filename may land outside the expected local_rel (e.g. the
        # repo-root ``rmvpe.pt`` must move into the ``rmvpe/`` subdirectory).
        fetched = assets_dir / remote_path
        if fetched.exists() and not force:
            fetched.unlink()
        hf_hub_download(
            repo_id=REPO_ID,
            filename=remote_path,
            revision=REVISION,
            local_dir=str(assets_dir),
        )
        if fetched != local_path:
            if not fetched.exists():
                raise FileNotFoundError(
                    f"Expected downloaded file at {fetched} but it is missing "
                    f"(local_dir placed it elsewhere for {remote_path!r})"
                )
            local_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(fetched), str(local_path))
        downloaded.append(str(local_path))
        logger.info("OK: %s", local_path)
    return downloaded


def all_assets_present() -> bool:
    assets_dir = get_engine_assets_dir()
    return all((assets_dir / local_rel).exists() for local_rel in ASSET_FILES.values())


if __name__ == "__main__":
    force = "--force" in sys.argv
    try:
        files = download_assets(force=force)
        ffmpeg_files = download_ffmpeg(force=force)
    except Exception as e:
        logger.error("Asset download failed: %s", e)
        sys.exit(1)
    if files:
        logger.info("Downloaded %d asset(s)", len(files))
    else:
        logger.info("All assets already present. Use --force to redownload.")
    logger.info("Assets dir: %s", get_engine_assets_dir())
