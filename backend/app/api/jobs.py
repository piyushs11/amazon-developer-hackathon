"""Publish jobs: POST /publish starts one, GET /publish/{job_id} reads its progress.

publish() takes a while (generate, verify with Bedrock, deploy), so the route returns a job id
at once and the work runs as a background task. Jobs live in this process's memory (fine for one
gateway instance; they are lost on restart, and the user simply publishes again: a service
that already went live is reported as "skipped"). Finished jobs are dropped after `ttl` seconds.
"""
import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.app.api.schemas import JobError, PublishStatus

log = logging.getLogger("mcp_bridge.api")


@dataclass
class Job:
    id: str
    user_id: str
    service_uuid: str
    status: str = "running"
    stage: str = "queued"
    mcp_url: str | None = None
    skipped: bool = False
    version: str | None = None
    error: JobError | None = None
    finished_at: float | None = None
    created_at: float = field(default_factory=time.monotonic)

    def to_status(self) -> PublishStatus:
        return PublishStatus(
            status=self.status, stage=self.stage, mcp_url=self.mcp_url, skipped=self.skipped,
            version=self.version, error=self.error,
        )


class PublishJobs:
    def __init__(self, publish: Callable | None = None, *, ttl: float = 3600.0,
                 clock: Callable[[], float] = time.monotonic):
        self._publish = publish  # tests inject a fake; default is pipeline.publish.publish
        self._ttl = ttl
        self._clock = clock
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()  # keeps running tasks from being garbage collected

    def _publish_fn(self):
        if self._publish is None:
            from backend.app.pipeline.publish import publish

            return publish
        return self._publish

    def _drop_old(self) -> None:
        now = self._clock()
        for job_id, job in list(self._jobs.items()):
            if job.finished_at is not None and now - job.finished_at > self._ttl:
                del self._jobs[job_id]

    def start(self, user_id: str, service_uuid: str) -> Job:
        """Start publishing, or return this user's running job for the same service.

        Must be called from inside the event loop (the route handler)."""
        self._drop_old()
        for job in self._jobs.values():
            if job.user_id == user_id and job.service_uuid == service_uuid and job.status == "running":
                return job
        job = Job(id=uuid.uuid4().hex, user_id=user_id, service_uuid=service_uuid)
        self._jobs[job.id] = job
        task = asyncio.get_running_loop().create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def get(self, job_id: str, user_id: str) -> Job | None:
        """The job, only for the user who started it (anyone else gets None -> 404)."""
        job = self._jobs.get(job_id)
        return job if job is not None and job.user_id == user_id else None

    async def _run(self, job: Job) -> None:
        def on_progress(stage: str) -> None:
            job.stage = stage

        try:
            result = await self._publish_fn()(job.user_id, job.service_uuid, on_progress)
        except Exception:
            log.exception("publish job crashed service_uuid=%s", job.service_uuid)
            job.status, job.stage = "failed", "failed"
            job.error = JobError(step="publish", code="INTERNAL_ERROR",
                                 message="Publishing failed unexpectedly. Please try again.")
        else:
            job.status, job.stage = result.status, result.status
            job.mcp_url, job.skipped, job.version = result.mcp_url, result.skipped, result.version
            if result.error is not None:
                job.error = JobError(**result.error.model_dump())
        job.finished_at = self._clock()


_jobs: PublishJobs | None = None


def get_jobs() -> PublishJobs:
    global _jobs
    if _jobs is None:
        _jobs = PublishJobs()
    return _jobs


def set_jobs(jobs: PublishJobs | None) -> None:
    """Tests: replace (or with None, reset) the process-wide job tracker."""
    global _jobs
    _jobs = jobs
