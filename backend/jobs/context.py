"""Execution context handed to job handlers and providers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.core.errors import JobCancelledError

ProgressSink = Callable[[float, str], None]


class JobContext:
    """Progress reporting + cooperative cancellation for one job (or one workflow step).

    ``child(start, end)`` maps the 0..1 progress of a sub-task into a slice of
    the parent's progress, so multi-step workflows show one continuous bar.
    """

    def __init__(
        self,
        job_id: str,
        output_dir: Path,
        sink: ProgressSink | None = None,
        cancel_event: asyncio.Event | None = None,
        logger: logging.Logger | None = None,
        *,
        _offset: float = 0.0,
        _scale: float = 1.0,
        _prefix: str = "",
        shared: dict[str, Any] | None = None,
    ) -> None:
        self.job_id = job_id
        self.output_dir = output_dir
        self._sink = sink
        self.cancel_event = cancel_event or asyncio.Event()
        self.logger = logger or logging.getLogger(f"job.{job_id[:8]}")
        self._offset = _offset
        self._scale = _scale
        self._prefix = _prefix
        self.shared: dict[str, Any] = shared if shared is not None else {}
        self.last_fraction = 0.0

    # -- progress ----------------------------------------------------------
    def report(self, fraction: float, message: str = "") -> None:
        fraction = max(0.0, min(1.0, float(fraction)))
        self.last_fraction = fraction
        if self._sink:
            text = f"{self._prefix}{message}" if message else self._prefix.rstrip(": ")
            self._sink(self._offset + fraction * self._scale, text)

    async def progress(self, fraction: float, message: str = "") -> None:
        self.report(fraction, message)
        await asyncio.sleep(0)

    # -- cancellation ------------------------------------------------------
    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelledError("Job was cancelled")

    # -- structure -----------------------------------------------------------
    def child(self, start: float, end: float, prefix: str = "") -> JobContext:
        start = max(0.0, min(1.0, start))
        end = max(start, min(1.0, end))
        return JobContext(
            self.job_id,
            self.output_dir,
            self._sink,
            self.cancel_event,
            self.logger,
            _offset=self._offset + start * self._scale,
            _scale=(end - start) * self._scale,
            _prefix=f"{prefix}: " if prefix else self._prefix,
            shared=self.shared,
        )

    @classmethod
    def detached(cls, output_dir: Path, job_id: str = "adhoc") -> JobContext:
        """Context for synchronous calls outside the queue (tests, CLI)."""
        output_dir.mkdir(parents=True, exist_ok=True)
        return cls(job_id, output_dir)
