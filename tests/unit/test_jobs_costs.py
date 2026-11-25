"""Job queue (retry, cancel, timeout, recovery, events) and cost control."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from backend.core.costs import CostGuard, ResourceEstimate
from backend.core.db import Database
from backend.core.errors import (
    BudgetExceededError,
    CostConfirmationRequiredError,
    ProviderDisabledError,
    ProviderUnavailableError,
    ValidationError,
)
from backend.jobs import JobContext, JobQueue, JobStatus
from backend.providers.base import ProviderInfo


@pytest.fixture
async def queue(tmp_path: Path):
    db = Database(tmp_path / "q.db")
    q = JobQueue(db, tmp_path / "out", max_attempts=3, retry_backoff_s=0.01, default_timeout_s=5)
    yield q
    await q.stop()


async def test_success_progress_and_events(queue: JobQueue) -> None:
    async def handler(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        for i in range(3):
            await ctx.progress((i + 1) / 3, f"step {i}")
        return {"echo": params["x"]}

    queue.register("t.ok", handler, resource="cpu")
    events = queue.subscribe()
    await queue.start()
    job = await queue.submit("t.ok", {"x": 42})
    done = await queue.wait(job.id, timeout=5)
    assert done.status == JobStatus.SUCCEEDED and done.result == {"echo": 42} and done.progress == 1.0
    kinds = []
    while not events.empty():
        kinds.append((await events.get())["event"])
    assert kinds[0] == "job.created" and "job.progress" in kinds


async def test_retry_only_for_retryable(queue: JobQueue) -> None:
    calls = {"flaky": 0, "bad": 0}

    async def flaky(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        calls["flaky"] += 1
        if calls["flaky"] < 3:
            raise ProviderUnavailableError("comfy down")
        return {"ok": True}

    async def bad(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        calls["bad"] += 1
        raise ValidationError("wrong input")

    queue.register("t.flaky", flaky, resource="cpu")
    queue.register("t.bad", bad, resource="cpu")
    await queue.start()
    j1 = await queue.wait((await queue.submit("t.flaky", {})).id, timeout=5)
    j2 = await queue.wait((await queue.submit("t.bad", {})).id, timeout=5)
    assert j1.status == JobStatus.SUCCEEDED and j1.attempts == 3
    assert j2.status == JobStatus.FAILED and j2.attempts == 1 and j2.error["code"] == "validation_error"
    assert calls == {"flaky": 3, "bad": 1}


async def test_crash_is_reported_not_raised(queue: JobQueue) -> None:
    async def crash(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        raise RuntimeError("boom")

    queue.register("t.crash", crash, resource="cpu")
    await queue.start()
    job = await queue.wait((await queue.submit("t.crash", {})).id, timeout=5)
    assert job.status == JobStatus.FAILED and "boom" in job.error["message"]


async def test_cancel_running_and_queued(queue: JobQueue) -> None:
    started = asyncio.Event()
    cancelled = {"seen": False}

    async def slow(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled["seen"] = True  # providers use this hook to interrupt engines
            raise
        return {}

    queue.register("t.slow", slow, resource="gpu")  # gpu pool = 1 → second job waits
    await queue.start()
    running = await queue.submit("t.slow", {})
    waiting = await queue.submit("t.slow", {})
    await asyncio.wait_for(started.wait(), 5)
    assert (await queue.cancel(waiting.id)).status == JobStatus.CANCELLED
    assert (await queue.cancel(running.id)).status == JobStatus.CANCELLED
    assert cancelled["seen"]
    retried = await queue.retry(running.id)
    assert retried.retry_of == running.id and retried.status == JobStatus.QUEUED
    await queue.cancel(retried.id)


async def test_timeout_is_retryable(tmp_path: Path) -> None:
    q = JobQueue(Database(tmp_path / "t.db"), tmp_path, max_attempts=2, retry_backoff_s=0.01)

    async def hang(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        await asyncio.sleep(10)
        return {}

    q.register("t.hang", hang, resource="cpu", timeout_s=0.2)
    await q.start()
    job = await q.wait((await q.submit("t.hang", {})).id, timeout=5)
    assert job.status == JobStatus.FAILED and job.error["code"] == "timeout" and job.attempts == 2
    await q.stop()


async def test_recovery_after_restart(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    q1 = JobQueue(db, tmp_path)

    async def h(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return {"done": True}

    q1.register("t.h", h, resource="cpu")
    queued = await q1.submit("t.h", {})  # never started
    db.execute("INSERT INTO jobs (id,type,status,resource,params,created_at,updated_at) VALUES "
               "('x1','t.h','running','cpu','{}','2026-01-01','2026-01-01')")
    q2 = JobQueue(db, tmp_path)
    q2.register("t.h", h, resource="cpu")
    await q2.start()
    assert (await q2.wait(queued.id, timeout=5)).status == JobStatus.SUCCEEDED
    assert q2.get("x1").status == JobStatus.FAILED and q2.get("x1").error["code"] == "interrupted"
    await q2.stop()


async def test_unknown_job_type(queue: JobQueue) -> None:
    with pytest.raises(ValidationError):
        await queue.submit("nope", {})


# ------------------------------------------------------------------- costs
def _guard(tmp_path: Path, budget: float = 10.0, per_job: float = 1.0) -> CostGuard:
    return CostGuard(Database(tmp_path / "c.db"), currency="USD", monthly_budget=budget, max_cost_per_job=per_job,
                     ttl_s=60, secret_path=tmp_path / "secret")


CLOUD = ProviderInfo(name="cloudy", display_name="Cloudy", location="cloud", cost_model="per_image", unit_cost=0.04,
                     requires_api_key=True, api_key_env="X", enabled=True)
LOCAL = ProviderInfo(name="local", display_name="Local")


def test_local_is_free(tmp_path: Path) -> None:
    g = _guard(tmp_path)
    est = g.estimate(LOCAL, "image.generate", count=4, resources=ResourceEstimate(est_seconds=10))
    assert est.is_free and not est.requires_confirmation and est.total_cost == 0
    g.authorize(LOCAL, est, None)


def test_paid_requires_valid_token(tmp_path: Path) -> None:
    g = _guard(tmp_path)
    est = g.estimate(CLOUD, "image.generate", model="m", count=3)
    assert est.total_cost == pytest.approx(0.12) and est.requires_confirmation and est.confirmation_token
    with pytest.raises(CostConfirmationRequiredError) as exc:
        g.authorize(CLOUD, est, None)
    assert exc.value.details["estimate"]["total_cost"] == pytest.approx(0.12)
    with pytest.raises(CostConfirmationRequiredError):
        g.authorize(CLOUD, est, "forged-token")
    other = g.estimate(CLOUD, "image.generate", model="m", count=10)  # token bound to the estimate
    with pytest.raises((CostConfirmationRequiredError, BudgetExceededError)):
        g.authorize(CLOUD, other, est.confirmation_token)
    g.authorize(CLOUD, est, est.confirmation_token)
    g.record(est, "job1")
    assert g.summary()["spent_this_month"] == pytest.approx(0.12)


def test_budget_rules(tmp_path: Path) -> None:
    zero = _guard(tmp_path, budget=0)
    est = zero.estimate(CLOUD, "image.generate", count=1)
    with pytest.raises(BudgetExceededError):
        zero.authorize(CLOUD, est, est.confirmation_token)
    per_job = _guard(tmp_path / "b", budget=100, per_job=0.05)
    est = per_job.estimate(CLOUD, "image.generate", count=5)
    with pytest.raises(BudgetExceededError):
        per_job.authorize(CLOUD, est, est.confirmation_token)
    disabled = CLOUD.model_copy(update={"enabled": False})
    g = _guard(tmp_path / "c")
    est = g.estimate(disabled, "image.generate")
    with pytest.raises(ProviderDisabledError):
        g.authorize(disabled, est, est.confirmation_token)


def test_expired_token(tmp_path: Path) -> None:
    g = CostGuard(Database(tmp_path / "e.db"), currency="USD", monthly_budget=10, max_cost_per_job=1, ttl_s=-1,
                  secret_path=tmp_path / "s")
    est = g.estimate(CLOUD, "image.generate")
    with pytest.raises(CostConfirmationRequiredError):
        g.authorize(CLOUD, est, est.confirmation_token)


async def test_studio_cost_flow_with_mock_cloud(studio: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A paid provider can only run with budget + confirmation; the charge is recorded after success."""
    from backend.providers.mock import MockImageProvider

    info = CLOUD.model_copy(update={"name": "mockcloud", "api_key_env": "MOCKCLOUD_KEY", "roles": ["image"]})
    monkeypatch.setenv("MOCKCLOUD_KEY", "test")
    studio.registry.register_instance("mockcloud", "image", MockImageProvider(info, studio.settings), info)
    params = {"prompt": "paid", "provider": "mockcloud", "batch_size": 2}
    with pytest.raises(BudgetExceededError):  # default budget 0
        await studio.submit("image.generate", params)
    studio.costs.monthly_budget = 5.0
    with pytest.raises(CostConfirmationRequiredError) as exc:
        await studio.submit("image.generate", params)
    token = exc.value.details["estimate"]["confirmation_token"]
    job = await studio.submit("image.generate", {**params, "confirm_token": token})
    assert "confirm_token" not in job.params
    done = await studio.queue.wait(job.id, timeout=20)
    assert done.status.value == "succeeded", done.error
    assert studio.costs.summary()["by_provider"]["mockcloud"]["total"] == pytest.approx(0.08)
