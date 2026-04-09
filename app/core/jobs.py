import uuid
from datetime import datetime, timezone

_jobs: dict[str, dict] = {}


def create_job(name: str) -> str:
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "job_id": job_id,
        "name": name,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
        "error": None,
    }
    return job_id


def start_job(job_id: str) -> None:
    if job_id in _jobs:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()


def finish_job(job_id: str, result: dict) -> None:
    if job_id in _jobs:
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["result"] = result
        _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


def fail_job(job_id: str, error: str) -> None:
    if job_id in _jobs:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = error
        _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)
