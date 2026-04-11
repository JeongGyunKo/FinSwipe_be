import uuid
from datetime import datetime, timezone

_jobs: dict[str, dict] = {}
_JOB_TTL_SECONDS = 7200  # 완료된 job 2시간 후 정리


def _cleanup_jobs() -> None:
    now = datetime.now(timezone.utc).timestamp()
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
