"""Typed error hierarchy shared by API, MCP server, job queue and providers.

Every error carries a stable machine-readable ``code``, an HTTP status and a
``retryable`` flag that the job queue uses to decide on automatic retries.
"""

from __future__ import annotations

from typing import Any


class StudioError(Exception):
    code = "studio_error"
    http_status = 500
    retryable = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationError(StudioError):
    code = "validation_error"
    http_status = 400


class NotFoundError(StudioError):
    code = "not_found"
    http_status = 404


class PathNotAllowedError(StudioError):
    code = "path_not_allowed"
    http_status = 403


class CapabilityNotSupportedError(StudioError):
    code = "capability_not_supported"
    http_status = 400


class ProviderUnavailableError(StudioError):
    """The provider (e.g. ComfyUI) is not reachable right now – worth retrying."""

    code = "provider_unavailable"
    http_status = 503
    retryable = True


class ProviderDisabledError(StudioError):
    code = "provider_disabled"
    http_status = 403


class ModelNotInstalledError(StudioError):
    code = "model_not_installed"
    http_status = 409


class HardwareInsufficientError(StudioError):
    code = "hardware_insufficient"
    http_status = 409


class ToolNotFoundError(StudioError):
    """A required external program (ffmpeg, blender, npx) is not installed."""

    code = "tool_not_found"
    http_status = 503


class ExternalProcessError(StudioError):
    code = "external_process_error"
    http_status = 500


class GenerationError(StudioError):
    """The generation engine reported an error while executing a workflow."""

    code = "generation_error"
    http_status = 500


class StudioTimeoutError(StudioError):
    code = "timeout"
    http_status = 504
    retryable = True


class CostConfirmationRequiredError(StudioError):
    """A paid action needs an explicit confirmation token from the user."""

    code = "cost_confirmation_required"
    http_status = 402


class BudgetExceededError(StudioError):
    code = "budget_exceeded"
    http_status = 402


class JobCancelledError(StudioError):
    code = "job_cancelled"
    http_status = 409


class AuthError(StudioError):
    code = "unauthorized"
    http_status = 401
