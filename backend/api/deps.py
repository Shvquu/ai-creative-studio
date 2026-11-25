from __future__ import annotations

from fastapi import Request

from backend.orchestration.studio import Studio


def get_studio(request: Request) -> Studio:
    return request.app.state.studio
