"""RVC training / inference orchestration.

Builds and runs the RVC engine's subprocess pipeline. Each stage (preprocess,
feature extraction, training, index building, inference) is a separate
subprocess so a failure in any stage is contained, and progress lines are
tailed to update the ``vc_jobs`` row for the UI.
"""

import asyncio
import logging
import os
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from ...config import (
    get_rvc_engine_dir,
    get_vc_dir,
    get_vc_models_dir,
    get_vc_results_dir,
    get_vc_uploads_dir,
)
from ...database import SessionLocal, VCJob as DBVCJob, VCModel as DBVCModel
from .gpu import get_rvc_python, require_engine_ready
from .jobs import _append_job_message, _update_job

logger = logging.getLogger(__name__)

# RVC assets live inside the engine directory (self-contained).
ENGINE_ASSETS = get_rvc_engine_dir() / "assets"
LOGS_DIR = get_rvc_engine_dir() / "logs"
WEIGHTS_DIR = get_rvc_engine_dir() / "assets" / "weights"
INDICES_DIR = get_rvc_engine_dir() / "logs"

# RVC supports training at 40k or 48k sample rate.
SUPPORTED_SAMPLE_RATES = {40000, 48000}


def _require_cuda() -> None:
    require_engine_ready()


def _preflight_assets(sample_rate: int = 40000) -> None:
    """Ensure the engine's pretrained assets exist before training."""
    sr_label = f"{sample_rate // 1000}k"
    missing = []
    for name in (
        "hubert_base/pytorch_model.bin",
        "rmvpe/rmvpe.pt",
        f"pretrained_v2/f0G{sr_label}.pth",
        f"pretrained_v2/f0D{sr_label}.pth",
    ):
        if not (ENGINE_ASSETS / name).exists():
            missing.append(name)
    if missing:
        raise RuntimeError(
            "RVC engine assets missing; run the asset downloader first: " + ", ".join(missing)
        )


# ---------------------------------------------------------------------------
# Training pipeline
# ---------------------------------------------------------------------------

async def run_train_job(job_id: str, model_id: str, dataset_dir: Path, opts: dict) -> None:
    """Run the full RVC training pipeline for a dataset directory.

    opts keys:
        name            model name (unique)
        sample_rate     40000 | 48000
        total_epochs    number of epochs (default 100)
        batch_size      max 4 for 8GB VRAM
        f0_method       rmvpe (default) | harvest
    """
    _require_cuda()
    python = get_rvc_python()
    engine_dir = get_rvc_engine_dir()
    sample_rate = int(opts.get("sample_rate", 40000))
    if sample_rate not in SUPPORTED_SAMPLE_RATES:
        sample_rate = 40000
    _preflight_assets(sample_rate)
    total_epochs = int(opts.get("total_epochs", 100))
    batch_size = max(1, min(int(opts.get("batch_size", 4)), 4))
    model_name = str(opts.get("name", model_id)).strip()
    version = "v2"
    f0method = "rmvpe"
    sr_label = f"{sample_rate // 1000}k"  # engine configs use "40k"/"48k" naming

    exp_dir = LOGS_DIR / model_id
    if exp_dir.exists():
        shutil.rmtree(exp_dir)
    exp_dir.mkdir(parents=True, exist_ok=True)

    _update_job(job_id, status="running", stage="preprocessing", progress=0.0, message="")

    def make_config():
        # The engine expects a config.json inside the experiment dir. The
        # bundled configs/v2/40k.json is the template for a 40k v2 model.
        config_src = engine_dir / "configs" / "v2" / f"{sr_label}.json"
        config_dst = exp_dir / "config.json"
        if config_src.exists():
            shutil.copy(config_src, config_dst)
        else:
            raise RuntimeError(f"No training config template for {sr_label} (v2)")

    make_config()

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["PYTHONUNBUFFERED"] = "1"

    # 1. Preprocess (slicing, resampling, denoising to 3s chunks)
    from .jobs import _run_vc_process

    rc = await _run_vc_process(
        job_id,
        [
            str(python),
            str(engine_dir / "train" / "preprocess.py"),
            str(dataset_dir),
            str(sample_rate),
            "1",  # n_p (processes)
            str(exp_dir),
            "True",  # noparallel
            "3.0",  # per (seconds)
        ],
        cwd=engine_dir,
        env=env,
        stage="preprocessing",
        progress_regex=None,
    )
    if rc != 0:
        _update_job(job_id, status="failed", stage="preprocessing", error="Preprocessing failed")
        return

    # 2. F0 extraction
    _update_job(job_id, stage="feature_extraction", progress=5.0)
    rc = await _run_vc_process(
        job_id,
        [
            str(python),
            str(engine_dir / "train" / "dataset" / "extract_f0.py"),
            "cuda",
            "1",
            "0",
            "0",
            str(exp_dir),
            "True",  # is_half
        ],
        cwd=engine_dir,
        env=env,
        stage="feature_extraction",
        progress_regex=None,
    )
    if rc != 0:
        _update_job(job_id, status="failed", stage="feature_extraction", error="F0 extraction failed")
        return

    # 3. HuBERT feature extraction
    rc = await _run_vc_process(
        job_id,
        [
            str(python),
            str(engine_dir / "train" / "dataset" / "extract_hubert_feature.py"),
            "cuda",
            "1",
            "0",
            "0",
            str(exp_dir),
            version,
            "True",  # is_half
        ],
        cwd=engine_dir,
        env=env,
        stage="feature_extraction",
        progress_regex=None,
    )
    if rc != 0:
        _update_job(job_id, status="failed", stage="feature_extraction", error="HuBERT extraction failed")
        return

    # 4. Training
    _update_job(job_id, stage="training", progress=10.0)
    pretrain_g = ENGINE_ASSETS / "pretrained_v2" / f"f0G{sr_label}.pth"
    pretrain_d = ENGINE_ASSETS / "pretrained_v2" / f"f0D{sr_label}.pth"
    _write_filelist(exp_dir, sample_rate)
    rc = await _run_vc_process(
        job_id,
        [
            str(python),
            str(engine_dir / "train" / "train.py"),
            "-e", model_id,
            "-sr", sr_label,
            "-f0", "1",
            "-bs", str(batch_size),
            "-g", "0",
            "-te", str(total_epochs),
            "-se", str(max(10, total_epochs // 10)),
            "-pg", str(pretrain_g),
            "-pd", str(pretrain_d),
            "-l", "1",  # if_latest
            "-c", "0",  # if_cache_data_in_gpu
            "-sw", "1",  # save weights
            "-v", version,
        ],
        cwd=engine_dir,
        env=env,
        stage="training",
        progress_regex=None,
    )
    if rc != 0:
        _update_job(job_id, status="failed", stage="training", error="Training failed")
        return

    # 5. Index building
    _update_job(job_id, stage="indexing", progress=95.0)
    rc = await _run_vc_process(
        job_id,
        [
            str(python),
            str(engine_dir / "train" / "train_index.py"),
            model_id,
            version,
            str(INDICES_DIR),
            "1",  # n_cpu
            "auto",
        ],
        cwd=engine_dir,
        env=env,
        stage="indexing",
        progress_regex=None,
    )
    if rc != 0:
        _update_job(job_id, status="failed", stage="indexing", error="Index building failed")
        return

    # 6. Move artifacts into the model directory
    await _finalize_model(job_id, model_id, model_name, exp_dir, sample_rate, total_epochs)


def _write_filelist(exp_dir: Path, sample_rate: int) -> None:
    """Generate the engine's ``filelist.txt`` from the preprocessed dataset.

    The vendored engine's ``train/utils.get_hparams()`` points
    ``hps.data.training_files`` at ``<exp_dir>/filelist.txt`` and the RVC
    dataloader expects one line per chunk:
        <gt_wav>|<3_feature768 npy>|<2a_f0 npy>|<2b-f0nsf npy>|<spk_id>
    ``preprocess.py`` does not write this file, so we generate it here by
    matching each ``0_gt_wavs`` chunk with its extracted features.
    """
    gt_wavs = exp_dir / "0_gt_wavs"
    feat768 = exp_dir / "3_feature768"
    f0_dir = exp_dir / "2a_f0"
    f0nsf_dir = exp_dir / "2b-f0nsf"

    chunks = sorted(p.name for p in gt_wavs.glob("*.wav")) if gt_wavs.is_dir() else []
    if not chunks:
        raise RuntimeError("Preprocessing produced no chunks under 0_gt_wavs/")

    lines = []
    for name in chunks:
        stem = name.removesuffix(".wav")
        wav = gt_wavs / name
        # Note: extract_hubert_feature.py writes 3_feature768/{stem}.npy
        # (stem, no extension), while extract_f0.py writes 2a_f0/{name}.npy
        # and 2b-f0nsf/{name}.npy (filename WITH extension).
        feat = feat768 / f"{stem}.npy"
        f0 = f0_dir / f"{name}.npy"
        f0nsf = f0nsf_dir / f"{name}.npy"
        if not (feat.exists() and f0.exists() and f0nsf.exists()):
            raise RuntimeError(
                f"Missing features for chunk {name}: hubert={feat.exists()}, "
                f"f0={f0.exists()}, f0nsf={f0nsf.exists()}"
            )
        lines.append(f"{wav}|{feat}|{f0}|{f0nsf}|0")

    (exp_dir / "filelist.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _finalize_model(
    job_id: str,
    model_id: str,
    model_name: str,
    exp_dir: Path,
    sample_rate: int,
    total_epochs: int,
) -> None:
    """Move the trained .pth + .index into data/vc/models/<model_id>/."""
    model_dir = get_vc_models_dir() / model_id
    model_dir.mkdir(parents=True, exist_ok=True)

    # The engine's train.py (with `-sw 1`) exports the inference-ready model
    # via `savee()` into <engine>/assets/weights/<exp_name>.pth. Prefer that;
    # fall back to the raw G_*.pth checkpoint if savee did not run.
    pth_src = WEIGHTS_DIR / f"{model_id}.pth"
    if not pth_src.exists():
        candidates = sorted(exp_dir.glob("G_*.pth"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            _update_job(job_id, status="failed", stage="done", error="No model checkpoint produced")
            return
        pth_src = candidates[0]

    pth_dst = model_dir / f"{model_name}.pth"
    shutil.copy(pth_src, pth_dst)

    # The engine writes added_IVF*.index inside the exp dir (and hard-links a
    # copy into <engine>/logs/). Copy the newest one next to the .pth.
    index_src = None
    for pattern in (exp_dir.glob("added_IVF*.index"), INDICES_DIR.glob(f"*{model_id}*.index")):
        for match in sorted(pattern, key=lambda p: p.stat().st_mtime, reverse=True):
            index_src = match
            break
        if index_src:
            break
    index_dst = None
    if index_src is not None:
        index_dst = model_dir / f"{model_name}.index"
        shutil.copy(index_src, index_dst)

    db = SessionLocal()
    try:
        vc_model = db.query(DBVCModel).filter_by(id=model_id).first()
        if vc_model is not None:
            vc_model.pth_path = str(pth_dst)
            vc_model.index_path = str(index_dst) if index_dst else None
            vc_model.name = model_name
            vc_model.version = "v2"
            vc_model.sample_rate = sample_rate
            vc_model.total_epochs = total_epochs
            vc_model.status = "ready"
            vc_model.updated_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()

    _update_job(
        job_id,
        status="done",
        stage="done",
        progress=100.0,
        finished_at=datetime.now(timezone.utc),
        message="Training complete",
    )
    logger.info("VC model %s (%s) ready at %s", model_name, model_id, pth_dst)


# ---------------------------------------------------------------------------
# Inference pipeline
# ---------------------------------------------------------------------------

async def run_convert_job(
    job_id: str,
    model_id: str,
    source_path: Path,
    opts: dict,
) -> None:
    """Run RVC inference: convert a source voice into the model's timbre."""
    _require_cuda()

    python = get_rvc_python()
    engine_dir = get_rvc_engine_dir()

    db = SessionLocal()
    try:
        vc_model = db.query(DBVCModel).filter_by(id=model_id).first()
        if vc_model is None:
            _update_job(job_id, status="failed", error="Model not found")
            return
        pth_path = Path(vc_model.pth_path)
        index_path = Path(vc_model.index_path) if vc_model.index_path else None
        version = vc_model.version or "v2"
    finally:
        db.close()

    if not pth_path.exists():
        _update_job(job_id, status="failed", error="Model weights missing on disk")
        return

    _update_job(job_id, status="running", stage="converting", progress=5.0, message="")

    f0_method = str(opts.get("f0_method", "rmvpe"))
    if f0_method not in ("pm", "rmvpe"):
        # The vendored inference CLI only implements pm/rmvpe F0 extraction.
        f0_method = "rmvpe"
    index_rate = float(opts.get("index_rate", 0.75))
    pitch = int(opts.get("pitch", 0))
    protect = float(opts.get("protect", 0.33))

    result_name = f"{job_id}.wav"
    result_path = get_vc_results_dir() / result_name

    args = [
        str(python),
        str(engine_dir / "infer" / "cli.py"),
        "--model", str(pth_path),
        "--input", str(source_path),
        "--output", str(result_path),
        "--pitch", str(pitch),
        "--f0-method", f0_method,
        "--protect", str(protect),
        "--format", "wav",
    ]
    if index_path is not None and index_path.exists():
        args += ["--index", str(index_path), "--index-rate", str(index_rate)]
    else:
        # Without a .index the RVC engine cannot do retrieval; run with
        # index_rate=0 so conversion still works (timbre relies on the model).
        args += ["--index-rate", "0"]

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["PYTHONUNBUFFERED"] = "1"

    from .jobs import _run_vc_process

    rc = await _run_vc_process(
        job_id,
        args,
        cwd=engine_dir,
        env=env,
        stage="converting",
        progress_regex=None,
    )
    if rc != 0 or not result_path.exists():
        _update_job(job_id, status="failed", stage="converting", error="Conversion failed")
        return

    _update_job(
        job_id,
        status="done",
        stage="done",
        progress=100.0,
        result_path=str(result_path),
        finished_at=datetime.now(timezone.utc),
        message="Conversion complete",
    )
    logger.info("VC convert job %s -> %s", job_id, result_path)
