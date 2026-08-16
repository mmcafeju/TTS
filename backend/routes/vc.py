"""Voice-conversion (RVC) endpoints.

Flow:
  1. ``POST /api/vc/upload``     — upload dataset / source audio → file_id
  2. ``POST /api/vc/train``      — enqueue a training job (returns job_id)
  3. ``POST /api/vc/convert``    — enqueue a conversion job (returns job_id)
  4. ``GET  /api/vc/jobs/{id}``  — poll job status / progress
  5. ``GET  /api/vc/models``     — list trained models (My Models)
  6. ``GET  /api/vc/results/{id}`` — download a finished conversion
"""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models
from ..config import (
    get_vc_models_dir,
    get_vc_results_dir,
    get_vc_uploads_dir,
)
from ..database import SessionLocal, VCModel as DBVCModel, VCJob as DBVCJob
from ..services import vc
from ..services.vc.gpu import get_vc_gpu_status
from ..services.vc.pipeline import LOGS_DIR
from .audio import _audio_media_type

router = APIRouter()

UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB
ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".webm", ".opus"}
MAX_DATASET_SECONDS = 60 * 60  # 1 hour per file cap (generous)


def _upload_path(file_id: str) -> Path:
    return get_vc_uploads_dir() / f"{file_id}"


@router.post("/vc/upload", response_model=models.VCUploadResponse)
async def upload_vc_audio(
    file: UploadFile = File(...),
    purpose: str = Form("dataset"),
):
    """Upload an audio file for VC training (dataset) or conversion (source)."""
    from ..utils.audio import load_audio

    uploaded_ext = Path(file.filename or "").suffix.lower()
    if uploaded_ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format '{uploaded_ext}'. Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXTS))}",
        )

    file_id = str(uuid.uuid4())
    dest = _upload_path(f"{file_id}{uploaded_ext}")

    size = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            out.write(chunk)
            size += len(chunk)

    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    duration = None
    try:
        audio, sr = await asyncio.to_thread(load_audio, str(dest))
        duration = len(audio) / sr
        if duration > MAX_DATASET_SECONDS:
            dest.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"Audio too long ({duration:.0f}s > {MAX_DATASET_SECONDS}s cap)",
            )
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        # Not every upload is decodable by librosa (e.g. WebM); keep the file
        # and let the RVC preprocessor handle the conversion downstream.
        logger = __import__("logging").getLogger(__name__)
        logger.warning("Could not read uploaded audio duration for %s", file_id)

    return models.VCUploadResponse(
        file_id=file_id,
        filename=file.filename or dest.name,
        path=str(dest),
        size=size,
        duration=duration,
    )


@router.post("/vc/train", response_model=models.VCJobResponse)
async def train_vc_model(req: models.VCTrainRequest):
    """Enqueue an RVC training job. Runs serially behind the VC queue."""
    status = get_vc_gpu_status()
    if not status.get("engine_ready"):
        raise HTTPException(
            status_code=422,
            detail=f"RVC engine not ready: {status.get('reason', 'unknown')}",
        )
    if not status.get("can_train"):
        raise HTTPException(
            status_code=422,
            detail="Not enough free VRAM for training. Close other GPU apps and retry.",
        )

    # Build the dataset directory from uploaded files.
    dataset_dir = get_vc_uploads_dir() / f"dataset-{req.name}"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    found = []
    for file_id in req.file_ids:
        for src in get_vc_uploads_dir().glob(f"{file_id}.*"):
            dst = dataset_dir / src.name
            if not dst.exists():
                dst.hardlink_to(src) if dst.parent.exists() else None
            # hardlink may not work across cases; copy as fallback
            if not dst.exists():
                import shutil

                shutil.copy2(src, dst)
            found.append(dst)
    if not found:
        raise HTTPException(status_code=400, detail="No uploaded files found for the given file_ids")

    # Refuse duplicates.
    db = SessionLocal()
    try:
        existing = db.query(DBVCModel).filter(DBVCModel.name == req.name).first()
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"A model named '{req.name}' already exists")
    finally:
        db.close()

    model_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    db = SessionLocal()
    try:
        db.add(
            DBVCModel(
                id=model_id,
                name=req.name,
                pth_path="",
                version="v2",
                sample_rate=req.sample_rate,
                status="training",
            )
        )
        db.add(
            DBVCJob(
                id=job_id,
                kind="train",
                status="pending",
                model_id=model_id,
                stage="queued",
                progress=0.0,
            )
        )
        db.commit()
    finally:
        db.close()

    from ..services.vc.pipeline import run_train_job

    opts = {
        "name": req.name,
        "sample_rate": req.sample_rate,
        "total_epochs": req.total_epochs,
        "batch_size": req.batch_size,
        "f0_method": req.f0_method,
    }

    async def _train_worker():
        try:
            await run_train_job(job_id, model_id, dataset_dir, opts)
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.exception("VC training job %s failed", job_id)
            db = SessionLocal()
            try:
                job = db.query(DBVCJob).filter_by(id=job_id).first()
                if job is not None:
                    job.status = "failed"
                    job.error = str(e)
                    job.finished_at = datetime.now(timezone.utc)
                    db.commit()
                model = db.query(DBVCModel).filter_by(id=model_id).first()
                if model is not None:
                    model.status = "failed"
                    model.error = str(e)
                    db.commit()
            finally:
                db.close()

    vc.enqueue_vc_job(job_id, _train_worker())

    return models.VCJobResponse(id=job_id, kind="train", status="pending", model_id=model_id, stage="queued")


@router.post("/vc/convert", response_model=models.VCJobResponse)
async def convert_voice(req: models.VCConvertRequest):
    """Enqueue an RVC conversion job through a trained model."""
    status = get_vc_gpu_status()
    if not status.get("engine_ready"):
        raise HTTPException(
            status_code=422,
            detail=f"RVC engine not ready: {status.get('reason', 'unknown')}",
        )

    db = SessionLocal()
    try:
        vc_model = db.query(DBVCModel).filter_by(id=req.model_id).first()
        if vc_model is None:
            raise HTTPException(status_code=404, detail="Model not found")
    finally:
        db.close()

    source = next(get_vc_uploads_dir().glob(f"{req.file_id}.*"), None)
    if source is None:
        raise HTTPException(status_code=404, detail="Source audio not found")

    job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(
            DBVCJob(
                id=job_id,
                kind="convert",
                status="pending",
                model_id=req.model_id,
                stage="queued",
                progress=0.0,
                source_path=str(source),
                f0_method=req.f0_method,
                index_rate=req.index_rate,
                pitch=req.pitch,
                protect=req.protect,
            )
        )
        db.commit()
    finally:
        db.close()

    from ..services.vc.pipeline import run_convert_job

    opts = {
        "f0_method": req.f0_method,
        "index_rate": req.index_rate,
        "pitch": req.pitch,
        "protect": req.protect,
    }

    async def _convert_worker():
        try:
            await run_convert_job(job_id, req.model_id, source, opts)
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.exception("VC convert job %s failed", job_id)
            db = SessionLocal()
            try:
                job = db.query(DBVCJob).filter_by(id=job_id).first()
                if job is not None:
                    job.status = "failed"
                    job.error = str(e)
                    job.finished_at = datetime.now(timezone.utc)
                    db.commit()
            finally:
                db.close()

    vc.enqueue_vc_job(job_id, _convert_worker())

    return models.VCJobResponse(id=job_id, kind="convert", status="pending", model_id=req.model_id, stage="queued")


@router.get("/vc/jobs/{job_id}", response_model=models.VCJobResponse)
async def get_vc_job(job_id: str):
    """Get the current status/progress of a VC job."""
    job = vc.get_vc_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return models.VCJobResponse(**job)


@router.get("/vc/jobs", response_model=list[models.VCJobResponse])
async def list_vc_jobs(limit: int = 50):
    """List recent VC jobs (newest first)."""
    return [models.VCJobResponse(**j) for j in vc.get_vc_jobs(limit=limit)]


@router.get("/vc/models", response_model=list[models.VCModelResponse])
async def list_vc_models():
    """List trained RVC models."""
    db = SessionLocal()
    try:
        rows = db.query(DBVCModel).order_by(DBVCModel.created_at.desc()).all()
        return [
            models.VCModelResponse(
                id=m.id,
                name=m.name,
                version=m.version,
                sample_rate=m.sample_rate,
                total_epochs=m.total_epochs,
                dataset_seconds=m.dataset_seconds,
                status=m.status,
                error=m.error,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
            for m in rows
        ]
    finally:
        db.close()


@router.patch("/vc/models/{model_id}", response_model=models.VCModelResponse)
async def rename_vc_model(model_id: str, body: dict):
    """Rename a trained model."""
    new_name = (body.get("name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="name is required")

    db = SessionLocal()
    try:
        vc_model = db.query(DBVCModel).filter_by(id=model_id).first()
        if vc_model is None:
            raise HTTPException(status_code=404, detail="Model not found")
        duplicate = db.query(DBVCModel).filter(DBVCModel.name == new_name, DBVCModel.id != model_id).first()
        if duplicate is not None:
            raise HTTPException(status_code=409, detail=f"A model named '{new_name}' already exists")
        vc_model.name = new_name
        db.commit()
        db.refresh(vc_model)
        return models.VCModelResponse(
            id=vc_model.id,
            name=vc_model.name,
            version=vc_model.version,
            sample_rate=vc_model.sample_rate,
            total_epochs=vc_model.total_epochs,
            dataset_seconds=vc_model.dataset_seconds,
            status=vc_model.status,
            error=vc_model.error,
            created_at=vc_model.created_at,
            updated_at=vc_model.updated_at,
        )
    finally:
        db.close()


@router.delete("/vc/models/{model_id}")
async def delete_vc_model(model_id: str):
    """Delete a trained model (DB row + files on disk)."""
    db = SessionLocal()
    try:
        vc_model = db.query(DBVCModel).filter_by(id=model_id).first()
        if vc_model is None:
            raise HTTPException(status_code=404, detail="Model not found")

        import shutil

        model_dir = get_vc_models_dir() / model_id
        if model_dir.exists():
            shutil.rmtree(model_dir)

        exp_dir = Path(LOGS_DIR) / model_id
        if exp_dir.exists():
            shutil.rmtree(exp_dir)

        # Cascade delete related jobs' result files, then the jobs.
        jobs = db.query(DBVCJob).filter(DBVCJob.model_id == model_id).all()
        for job in jobs:
            if job.result_path:
                result = Path(job.result_path)
                if result.exists():
                    result.unlink(missing_ok=True)
            db.delete(job)

        db.delete(vc_model)
        db.commit()
        return {"deleted": True}
    finally:
        db.close()


@router.get("/vc/results/{job_id}")
async def get_vc_result(job_id: str):
    """Download the result audio of a finished conversion job."""
    from ..services.vc.jobs import get_result_path

    result = get_result_path(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return FileResponse(
        str(result),
        media_type=_audio_media_type(result),
        filename=result.name,
    )


@router.get("/vc/status")
async def vc_status():
    """Engine + GPU readiness + current busy state."""
    status = get_vc_gpu_status()
    status["busy"] = vc.is_vc_busy()
    status["running_job_id"] = vc.get_running_vc_job()
    return status
