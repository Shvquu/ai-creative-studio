"""Persistent asynchronous job queue.

* One asyncio worker pool per resource class (``gpu``, ``cpu``, ``workflow``),
  each guarded by a semaphore that workflow steps can share.
* Jobs are persisted in SQLite; progress writes are throttled.
* Cancellation: queued jobs are skipped, running jobs get their task cancelled
  (providers translate that into engine-specific interrupts).
* Retries: only for errors flagged ``retryable`` (exponential backoff).
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.core.db import Database, to_json, utcnow
from backend.core.errors import JobCancelledError, NotFoundError, StudioError, StudioTimeoutError, ValidationError

from .context import JobContext
from .models import Job, JobStatus

log = logging.getLogger("jobs")

JobHandler = Callable[[dict[str, Any], JobContext], Awaitable[dict[str, Any]]]
RESOURCES = ("gpu", "cpu", "workflow")


@dataclass
class JobTypeSpec:
    name: str
    handler: JobHandler
    resource: str = "gpu"
    timeout_s: float | None = None
    max_attempts: int | None = None
    description: str = ""


class JobQueue:
    def __init__(
        self,
        db: Database,
        output_root: Path,
        *,
        concurrency: dict[str, int] | None = None,
        max_attempts: int = 2,
        retry_backoff_s: float = 5.0,
        default_timeout_s: float = 7200.0,
    ) -> None:
        self.db = db
        self.output_root = output_root
        self.concurrency = {"gpu": 1, "cpu": 2, "workflow": 2, **(concurrency or {})}
        self.max_attempts = max_attempts
        self.retry_backoff_s = retry_backoff_s
        self.default_timeout_s = default_timeout_s
        self.types: dict[str, JobTypeSpec] = {}
        self.semaphores = {r: asyncio.Semaphore(n) for r, n in self.concurrency.items()}
        self._queues: dict[str, asyncio.Queue[str]] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._running: dict[str, asyncio.Task[Any]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._cancel_requested: set[str] = set()
        self._done_events: dict[str, asyncio.Event] = {}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._last_persist: dict[str, float] = {}
        self._cache: dict[str, Job] = {}
        self.started = False

    # ------------------------------------------------------------------ setup
    def register(
        self,
        name: str,
        handler: JobHandler,
        *,
        resource: str = "gpu",
        timeout_s: float | None = None,
        max_attempts: int | None = None,
        description: str = "",
    ) -> None:
        if resource not in self.concurrency:
            raise ValueError(f"Unknown resource '{resource}'")
        self.types[name] = JobTypeSpec(name, handler, resource, timeout_s, max_attempts, description)

    async def start(self) -> None:
        if self.started:
            return
        self._queues = {r: asyncio.Queue() for r in self.concurrency}
        for resource, count in self.concurrency.items():
            for i in range(count):
                self._workers.append(asyncio.create_task(self._worker(resource), name=f"worker-{resource}-{i}"))
        self.started = True
        self._recover()

    async def stop(self) -> None:
        for task in list(self._running.values()):
            task.cancel()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self.started = False

    def _recover(self) -> None:
        """After a restart: running jobs → failed (retryable), queued jobs → re-enqueued."""
        for row in self.db.fetchall("SELECT * FROM jobs WHERE status IN ('running','retrying')"):
            err = {"code": "interrupted", "message": "Durch Neustart des Backends unterbrochen – bitte erneut starten (Retry)."}
            self.db.execute(
                "UPDATE jobs SET status=?, error=?, finished_at=?, updated_at=? WHERE id=?",
                (JobStatus.FAILED.value, to_json(err), utcnow(), utcnow(), row["id"]),
            )
        for row in self.db.fetchall("SELECT id, resource, type FROM jobs WHERE status='queued' ORDER BY created_at"):
            if row["type"] in self.types:
                self._queues[row["resource"]].put_nowait(row["id"])
                self._done_events.setdefault(row["id"], asyncio.Event())

    # ----------------------------------------------------------------- events
    def subscribe(self, maxsize: int = 1000) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    def _publish(self, job: Job, event: str = "job.updated") -> None:
        payload = {"event": event, "job": job.model_dump(mode="json")}
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------- persistence
    def _save(self, job: Job) -> None:
        job.updated_at = utcnow()
        self.db.execute(
            """INSERT INTO jobs (id,type,status,resource,params,result,error,progress,message,attempts,
                 max_attempts,provider,parent_id,retry_of,project,label,created_at,started_at,finished_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, result=excluded.result, error=excluded.error,
                 progress=excluded.progress, message=excluded.message, attempts=excluded.attempts,
                 provider=excluded.provider, started_at=excluded.started_at, finished_at=excluded.finished_at,
                 updated_at=excluded.updated_at""",
            (
                job.id, job.type, job.status.value, job.resource, to_json(job.params), to_json(job.result),
                to_json(job.error), job.progress, job.message, job.attempts, job.max_attempts, job.provider,
                job.parent_id, job.retry_of, job.project, job.label, job.created_at, job.started_at,
                job.finished_at, job.updated_at,
            ),
        )
        self._last_persist[job.id] = time.monotonic()
        if job.is_final:
            self._cache.pop(job.id, None)
        else:
            self._cache[job.id] = job

    # --------------------------------------------------------------- public API
    async def submit(
        self,
        job_type: str,
        params: dict[str, Any],
        *,
        provider: str | None = None,
        project: str | None = None,
        label: str | None = None,
        parent_id: str | None = None,
        retry_of: str | None = None,
    ) -> Job:
        spec = self.types.get(job_type)
        if spec is None:
            raise ValidationError(f"Unknown job type '{job_type}'", details={"known": sorted(self.types)})
        now = utcnow()
        job = Job(
            id=uuid.uuid4().hex,
            type=job_type,
            status=JobStatus.QUEUED,
            resource=spec.resource,
            params=params,
            max_attempts=spec.max_attempts or self.max_attempts,
            provider=provider,
            project=project,
            label=label,
            parent_id=parent_id,
            retry_of=retry_of,
            created_at=now,
            updated_at=now,
            message="Wartet in der Warteschlange",
        )
        self._save(job)
        self._done_events[job.id] = asyncio.Event()
        if self.started:
            self._queues[spec.resource].put_nowait(job.id)
        self._publish(job, "job.created")
        log.info("Job %s (%s) queued on %s", job.id[:8], job_type, spec.resource)
        return job

    def get(self, job_id: str) -> Job:
        if job_id in self._cache:
            return self._cache[job_id]
        row = self.db.fetchone("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not row:
            raise NotFoundError(f"Job not found: {job_id}")
        return Job.from_row(row)

    def list(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
        parent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Job]:
        where, args = [], []
        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            where.append(f"status IN ({','.join('?' * len(statuses))})")
            args += statuses
        if job_type:
            where.append("type LIKE ?")
            args.append(job_type.replace("*", "%"))
        if parent_id:
            where.append("parent_id=?")
            args.append(parent_id)
        sql = "SELECT * FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        args += [max(1, min(limit, 500)), max(0, offset)]
        jobs = [Job.from_row(r) for r in self.db.fetchall(sql, args)]
        return [self._cache.get(j.id, j) for j in jobs]

    def counts(self) -> dict[str, int]:
        rows = self.db.fetchall("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    async def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.is_final:
            return job
        self._cancel_requested.add(job_id)
        event = self._cancel_events.get(job_id)
        if event:
            event.set()
        task = self._running.get(job_id)
        if task is not None:
            task.cancel()
            done = self._done_events.get(job_id)
            if done:
                try:
                    await asyncio.wait_for(done.wait(), timeout=30)
                except asyncio.TimeoutError:
                    log.warning("Job %s did not stop within 30 s after cancel", job_id[:8])
            return self.get(job_id)
        # queued / retrying → finalize immediately
        job.status = JobStatus.CANCELLED
        job.message = "Abgebrochen"
        job.finished_at = utcnow()
        self._save(job)
        self._publish(job)
        self._finish(job_id)
        return job

    async def retry(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
            raise ValidationError(f"Only failed or cancelled jobs can be retried (status: {job.status.value})")
        return await self.submit(
            job.type, job.params, provider=job.provider, project=job.project, label=job.label,
            parent_id=job.parent_id, retry_of=job.id,
        )

    async def wait(self, job_id: str, timeout: float | None = None) -> Job:
        job = self.get(job_id)
        if job.is_final:
            return job
        event = self._done_events.setdefault(job_id, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return self.get(job_id)

    # ------------------------------------------------------------------ worker
    def _finish(self, job_id: str) -> None:
        self._cancel_requested.discard(job_id)
        self._cancel_events.pop(job_id, None)
        self._last_persist.pop(job_id, None)
        event = self._done_events.pop(job_id, None)
        if event:
            event.set()

    async def _worker(self, resource: str) -> None:
        queue = self._queues[resource]
        while True:
            job_id = await queue.get()
            try:
                job = self.get(job_id)
            except NotFoundError:
                continue
            if job.status != JobStatus.QUEUED:
                continue
            async with self.semaphores[resource]:
                await self._run(job)

    def _make_sink(self, job: Job) -> Callable[[float, str], None]:
        def sink(fraction: float, message: str) -> None:
            job.progress = round(max(job.progress, min(fraction, 0.999)), 4)
            if message:
                job.message = message
            job.updated_at = utcnow()
            if time.monotonic() - self._last_persist.get(job.id, 0) > 1.0:
                self._save(job)
            self._publish(job, "job.progress")

        return sink

    async def _run(self, job: Job) -> None:
        spec = self.types[job.type]
        timeout = spec.timeout_s or self.default_timeout_s
        cancel_event = asyncio.Event()
        self._cancel_events[job.id] = cancel_event
        output_dir = self.output_root
        ctx = JobContext(job.id, output_dir, self._make_sink(job), cancel_event, logging.getLogger(f"job.{job.type}"))

        while True:
            job.attempts += 1
            job.status = JobStatus.RUNNING
            job.started_at = job.started_at or utcnow()
            job.message = "Läuft" if job.attempts == 1 else f"Läuft (Versuch {job.attempts}/{job.max_attempts})"
            job.error = None
            self._save(job)
            self._publish(job)

            task = asyncio.create_task(spec.handler(job.params, ctx), name=f"job-{job.id[:8]}")
            self._running[job.id] = task
            error: StudioError | None = None
            try:
                done, _ = await asyncio.wait({task}, timeout=timeout)
            except asyncio.CancelledError:
                # Worker shutdown.
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                job.status = JobStatus.FAILED
                job.error = {"code": "interrupted", "message": "Backend wurde beendet"}
                job.finished_at = utcnow()
                self._save(job)
                self._running.pop(job.id, None)
                self._finish(job.id)
                raise
            finally:
                self._running.pop(job.id, None)

            if not done:
                task.cancel()
                cancel_event.set()
                await asyncio.gather(task, return_exceptions=True)
                cancel_event.clear()
                error = StudioTimeoutError(f"Zeitlimit von {int(timeout)} s überschritten")
            elif task.cancelled() or job.id in self._cancel_requested:
                job.status = JobStatus.CANCELLED
                job.message = "Abgebrochen"
                job.finished_at = utcnow()
                self._save(job)
                self._publish(job)
                self._finish(job.id)
                log.info("Job %s cancelled", job.id[:8])
                return
            else:
                exc = task.exception()
                if exc is None:
                    job.result = task.result() or {}
                    job.status = JobStatus.SUCCEEDED
                    job.progress = 1.0
                    job.message = "Fertig"
                    job.finished_at = utcnow()
                    self._save(job)
                    self._publish(job)
                    self._finish(job.id)
                    log.info("Job %s (%s) succeeded", job.id[:8], job.type)
                    return
                if isinstance(exc, JobCancelledError):
                    job.status = JobStatus.CANCELLED
                    job.message = "Abgebrochen"
                    job.finished_at = utcnow()
                    self._save(job)
                    self._publish(job)
                    self._finish(job.id)
                    return
                if isinstance(exc, StudioError):
                    error = exc
                else:
                    log.error("Job %s crashed: %s", job.id[:8], "".join(traceback.format_exception(exc)))
                    error = StudioError(f"{type(exc).__name__}: {exc}")

            assert error is not None
            job.error = {**error.to_dict(), "attempt": job.attempts}
            if error.retryable and job.attempts < job.max_attempts:
                delay = self.retry_backoff_s * (2 ** (job.attempts - 1))
                job.status = JobStatus.RETRYING
                job.message = f"Fehler: {error.message} – neuer Versuch in {delay:.0f} s"
                self._save(job)
                self._publish(job)
                log.warning("Job %s attempt %d failed (%s), retrying in %.0fs", job.id[:8], job.attempts, error.code, delay)
                try:
                    await asyncio.wait_for(cancel_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                if cancel_event.is_set() or job.id in self._cancel_requested:
                    job.status = JobStatus.CANCELLED
                    job.message = "Abgebrochen"
                    job.finished_at = utcnow()
                    self._save(job)
                    self._publish(job)
                    self._finish(job.id)
                    return
                continue

            job.status = JobStatus.FAILED
            job.message = error.message
            job.finished_at = utcnow()
            self._save(job)
            self._publish(job)
            self._finish(job.id)
            log.warning("Job %s (%s) failed: %s", job.id[:8], job.type, error.message)
            return
