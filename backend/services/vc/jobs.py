"""Single-slot job queue for the voice-conversion engine.

Training and conversion run in the RVC engine's dedicated subprocess (its
own venv).  Because RVC training is VRAM-hungry, only one VC job runs at a
time; jobs wait in an asyncio queue and each subprocess is isolated so an
OOM / crash never takes down FastAPI.

Progress is derived by tailing the RVC scripts' stdout (they emit per-file
"i/total" progress lines and per-epoch "Epoch: N/M" lines), and persisted
to the ``vc_jobs`` table so the UI can poll /api/vc/jobs/{id}.
"""

import asyncio
import logging
import os
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ...config import (
    get_vc_results_dir,
)
from ...database import SessionLocal, VCJob as DBVCJob, VCModel as DBVCModel
from .gpu import get_rvc_python

logger = logging.getLogger(__name__)

# Keep references to the worker task to prevent GC.
_vc_queue: asyncio.Queue | None = None
_vc_worker_task: asyncio.Task | None = None
_running_vc_job: str | None = None
_background_tasks: set = set()

# Stage order for training jobs (UI-facing progress text).
TRAIN_STAGES = ["queued", "preprocessing", "feature_extraction", "training", "indexing", "done"]

# Regexes used to extract progress from RVC subprocess output.
_PREPROCESS_PROGRESS = re.compile(r"(\d+)\s*/\s*(\d+)")
_F0_PROGRESS = re.compile(r"(\d+)\s*/\s*(\d+)")
_EPOCH_PROGRESS = re.compile(r"[Ee]poch\s*[:：]?\s*(\d+)\s*[/-]\s*(\d+)")
_EPOCH_BAR = re.compile(r"epoch\s+(\d+)/(\d+)")
_INDEX_PROGRESS = re.compile(r"(\d+)\s*/\s*(\d+)")


@dataclass
class VCJob:
    """Queued VC job payload."""

    job_id: str
    coro: object  # async callable OR a coroutine object


def create_background_task(coro) -> asyncio.Task:
    """Create a background task and prevent it from being garbage collected."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def init_vc_queue(force: bool = False) -> None:
    """Initialize the VC job queue and start its single worker."""
    global _vc_queue, _vc_worker_task
    if _vc_worker_task is not None and not _vc_worker_task.done():
        if not force:
            return
        _vc_worker_task.cancel()

    _vc_queue = asyncio.Queue()
    _vc_worker_task = create_background_task(_vc_worker())


async def _vc_worker() -> None:
    """Process one VC job at a time."""
    global _running_vc_job
    while True:
        job = await _vc_queue.get()
        _running_vc_job = job.job_id
        try:
            if asyncio.iscoroutine(job.coro):
                await job.coro
            else:
                await job.coro()
        except asyncio.CancelledError:
            logger.info("VC worker cancelled for job %s", job.job_id)
            raise
        except Exception:
            logger.exception("VC job %s failed unexpectedly", job.job_id)
        finally:
            _running_vc_job = None
            _vc_queue.task_done()


def enqueue_vc_job(job_id: str, coro) -> None:
    """Queue a VC job coroutine (serialized behind the single worker)."""
    if _vc_queue is None:
        raise RuntimeError("VC queue has not been initialized")
    _vc_queue.put_nowait(VCJob(job_id=job_id, coro=coro))


def is_vc_busy() -> bool:
    """Whether any VC job is currently running or queued."""
    if _running_vc_job is not None:
        return True
    return _vc_queue is not None and not _vc_queue.empty()


def get_running_vc_job() -> str | None:
    """Return the job id of the currently running VC job, if any."""
    return _running_vc_job


def cancel_vc_job(job_id: str) -> bool:
    """Cancel a queued VC job. Running subprocesses cannot be cancelled here
    (they live in a separate process); only queued jobs can be dropped."""
    global _vc_queue
    if _vc_queue is None:
        return False
    # Rebuild the queue without the matching job.
    remaining = []
    found = False
    while not _vc_queue.empty():
        item = _vc_queue.get_nowait()
        if item.job_id == job_id and not found:
            found = True
            _mark_job_cancelled(job_id)
            continue
        remaining.append(item)
    for item in remaining:
        _vc_queue.put_nowait(item)
    return found


def _mark_job_cancelled(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(DBVCJob).filter_by(id=job_id).first()
        if job is not None and job.status in ("pending", "queued"):
            job.status = "cancelled"
            job.stage = "cancelled"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _load_job(job_id: str) -> DBVCJob | None:
    db = SessionLocal()
    try:
        return db.query(DBVCJob).filter_by(id=job_id).first()
    finally:
        db.close()


def _update_job(job_id: str, **fields) -> None:
    db = SessionLocal()
    try:
        job = db.query(DBVCJob).filter_by(id=job_id).first()
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        db.commit()
    finally:
        db.close()


def _append_job_message(job_id: str, line: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(DBVCJob).filter_by(id=job_id).first()
        if job is None:
            return
        current = job.message or ""
        job.message = (current + line + "\n")[-4000:]
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------

async def _run_vc_process(
    job_id: str,
    args: list[str],
    *,
    cwd: Path,
    env: dict | None = None,
    stage: str | None = None,
    progress_total: int | None = None,
    progress_regex: re.Pattern | None = None,
) -> int:
    """Run an RVC engine script, streaming stdout into the job log.

    Returns the process return code. Progress lines matching ``progress_regex``
    update the job's ``progress`` field (0-100), where ``progress_total`` is
    the expected total count reported by the first match.
    """
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    # RVC scripts chdir into the engine root; make sure Python finds its deps.
    merged_env.setdefault("PYTHONUNBUFFERED", "1")

    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        env=merged_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    first_total: int | None = None
    async for raw_line in process.stdout:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
        if not line.strip():
            continue
        _append_job_message(job_id, line)

        if progress_regex is not None:
            match = progress_regex.search(line)
            if match:
                current = int(match.group(1))
                total = int(match.group(2))
                if first_total is None:
                    first_total = total
                if (first_total or total) > 0:
                    progress = min(100.0, round(current / first_total * 100, 1))
                    if stage:
                        _update_job(job_id, stage=stage, progress=progress)

    return await process.wait()


# ---------------------------------------------------------------------------
# Public orchestration helpers (called from routes)
# ---------------------------------------------------------------------------

def get_vc_job(job_id: str) -> dict | None:
    """Serialize a VC job for the API."""
    db = SessionLocal()
    try:
        job = db.query(DBVCJob).filter_by(id=job_id).first()
        if job is None:
            return None
        return {
            "id": job.id,
            "kind": job.kind,
            "status": job.status,
            "model_id": job.model_id,
            "stage": job.stage,
            "progress": job.progress,
            "message": job.message,
            "error": job.error,
            "result_path": job.result_path,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }
    finally:
        db.close()


def get_vc_jobs(limit: int = 50) -> list[dict]:
    """Serialize recent VC jobs, newest first."""
    db = SessionLocal()
    try:
        rows = (
            db.query(DBVCJob)
            .order_by(DBVCJob.created_at.desc())
            .limit(limit)
            .all()
        )
        result = []
        for job in rows:
            result.append(
                {
                    "id": job.id,
                    "kind": job.kind,
                    "status": job.status,
                    "model_id": job.model_id,
                    "stage": job.stage,
                    "progress": job.progress,
                    "message": job.message,
                    "error": job.error,
                    "result_path": job.result_path,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                }
            )
        return result
    finally:
        db.close()


def get_result_path(job_id: str) -> Path | None:
    """Resolve the result audio file for a completed convert job."""
    db = SessionLocal()
    try:
        job = db.query(DBVCJob).filter_by(id=job_id).first()
        if job is None or not job.result_path:
            return None
        path = Path(job.result_path)
        if not path.is_absolute():
            path = get_vc_results_dir() / path
        return path if path.exists() else None
    finally:
        db.close()
