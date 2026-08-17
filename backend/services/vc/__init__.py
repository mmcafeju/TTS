"""Voice-conversion (RVC) services.

Training and inference run in a dedicated subprocess against a separate
venv (backend/rvc_engine with its own installed dependencies) so a crash,
OOM, or CUDA fault inside the RVC engine can never take down the FastAPI
process. This module owns the single-slot job queue, subprocess orchestration,
and progress tracking derived from the RVC log files.
"""

from .jobs import (
    cancel_vc_job,
    enqueue_vc_job,
    get_running_vc_job,
    get_vc_job,
    get_vc_jobs,
    init_vc_queue,
    is_vc_busy,
)
from .pipeline import run_convert_job, run_train_job

__all__ = [
    "cancel_vc_job",
    "enqueue_vc_job",
    "get_running_vc_job",
    "get_vc_job",
    "get_vc_jobs",
    "init_vc_queue",
    "is_vc_busy",
    "run_convert_job",
    "run_train_job",
]
