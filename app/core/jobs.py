import threading
import uuid
from datetime import datetime, timezone
from typing import TypedDict


class JobInfo(TypedDict, total=False):
    job_id: str
    name: str
    status: str
    created_at: str
    started_at: str
    finished_at: str
    result: dict | None
    error: str | None


_jobs: dict[str, JobInfo] = {}
_jobs_lock = threading.Lock()
_JOB_TTL_SECONDS = 7200  # 완료된 job 2시간 후 정리


def _cleanup_jobs() -> None:
    now = datetime.now(timezone.utc).timestamp()
    with _jobs_lock:
        expired = [
            jid for jid, j in _jobs.items()
            if j["status"] in ("done", "failed")
            and j.get("finished_at")
            and (now - datetime.fromisoformat(j["finished_at"]).timestamp()) > _JOB_TTL_SECONDS
        ]
        for jid in expired:
            del _jobs[jid]


def create_job(name: str) -> str:
    _cleanup_jobs()
    job_id = str(uuid.uuid4())[:8]
    with _jobs_lock:
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
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()


def finish_job(job_id: str, result: dict) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result
            _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


def fail_job(job_id: str, error: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = error
            _jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


def get_job(job_id: str) -> JobInfo | None:
    with _jobs_lock:
        return _jobs.get(job_id)
