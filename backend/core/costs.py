"""Cost control.

* Every generation gets an estimate (money + expected resource usage).
* Free local providers pass straight through.
* Paid providers require: provider enabled, API key present, monthly budget > 0
  and not exceeded, per-job limit respected, and an explicit confirmation token
  that is bound to exactly this estimate (HMAC, short TTL).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .db import Database, utcnow
from .errors import BudgetExceededError, CostConfirmationRequiredError, ProviderDisabledError


class ResourceEstimate(BaseModel):
    vram_gb: float | None = None
    ram_gb: float | None = None
    est_seconds: float | None = None
    disk_mb: float | None = None
    note: str = ""


class CostEstimate(BaseModel):
    provider: str
    location: str
    operation: str
    model: str | None = None
    count: int = 1
    unit_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"
    is_free: bool = True
    requires_confirmation: bool = False
    confirmation_token: str | None = None
    budget_monthly: float | None = None
    budget_spent: float | None = None
    budget_remaining: float | None = None
    resources: ResourceEstimate = ResourceEstimate()


def _load_secret(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        data = path.read_bytes()
        if len(data) >= 32:
            return data
    data = secrets.token_bytes(32)
    path.write_bytes(data)
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - Windows
        pass
    return data


class CostGuard:
    def __init__(self, db: Database, *, currency: str, monthly_budget: float, max_cost_per_job: float,
                 ttl_s: int, secret_path: Path) -> None:
        self.db = db
        self.currency = currency
        self.monthly_budget = monthly_budget
        self.max_cost_per_job = max_cost_per_job
        self.ttl_s = ttl_s
        self._secret = _load_secret(secret_path)

    # ------------------------------------------------------------ estimates
    def spent_this_month(self) -> float:
        start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        row = self.db.fetchone("SELECT COALESCE(SUM(amount),0) AS s FROM cost_ledger WHERE created_at>=?", (start,))
        return float(row["s"]) if row else 0.0

    def estimate(self, info: Any, operation: str, *, model: str | None = None, count: int = 1,
                 resources: ResourceEstimate | None = None) -> CostEstimate:
        is_free = info.location == "local" and info.cost_model == "free"
        unit = 0.0 if is_free else float(info.unit_cost)
        total = round(unit * max(1, count), 4)
        est = CostEstimate(
            provider=info.name, location=info.location, operation=operation, model=model, count=count,
            unit_cost=unit, total_cost=total, currency=info.currency or self.currency, is_free=is_free or total == 0,
            requires_confirmation=not (is_free or total == 0), resources=resources or ResourceEstimate(),
        )
        if est.requires_confirmation:
            spent = self.spent_this_month()
            est.budget_monthly = self.monthly_budget
            est.budget_spent = round(spent, 4)
            est.budget_remaining = round(self.monthly_budget - spent, 4)
            est.confirmation_token = self._make_token(est)
        return est

    # --------------------------------------------------------------- tokens
    def _fingerprint(self, est: CostEstimate) -> str:
        payload = json.dumps([est.provider, est.operation, est.model, est.count, est.total_cost, est.currency])
        return hashlib.sha256(payload.encode()).hexdigest()

    def _make_token(self, est: CostEstimate) -> str:
        expiry = int(time.time()) + self.ttl_s
        msg = f"{self._fingerprint(est)}.{expiry}".encode()
        sig = hmac.new(self._secret, msg, hashlib.sha256).hexdigest()[:32]
        return base64.urlsafe_b64encode(f"{expiry}.{sig}".encode()).decode().rstrip("=")

    def _verify(self, est: CostEstimate, token: str) -> bool:
        try:
            padded = token + "=" * (-len(token) % 4)
            expiry_s, sig = base64.urlsafe_b64decode(padded.encode()).decode().split(".", 1)
            expiry = int(expiry_s)
        except Exception:
            return False
        if expiry < time.time():
            return False
        msg = f"{self._fingerprint(est)}.{expiry}".encode()
        expected = hmac.new(self._secret, msg, hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(expected, sig)

    # ---------------------------------------------------------- authorization
    def authorize(self, info: Any, est: CostEstimate, token: str | None) -> None:
        """Raise unless the action may run. Free local actions always pass."""
        if not est.requires_confirmation:
            return
        if not info.enabled:
            raise ProviderDisabledError(f"Kostenpflichtiger Provider '{info.name}' ist deaktiviert.")
        if self.monthly_budget <= 0:
            raise BudgetExceededError(
                "Kein Budget für kostenpflichtige Aktionen freigegeben (costs.monthly_budget = 0).",
                details={"estimate": est.model_dump()},
            )
        if est.total_cost > self.max_cost_per_job:
            raise BudgetExceededError(
                f"Geschätzte Kosten {est.total_cost:.2f} {est.currency} überschreiten das Limit pro Job "
                f"({self.max_cost_per_job:.2f}).", details={"estimate": est.model_dump()},
            )
        if (est.budget_remaining or 0) < est.total_cost:
            raise BudgetExceededError("Monatsbudget würde überschritten.", details={"estimate": est.model_dump()})
        if not token or not self._verify(est, token):
            raise CostConfirmationRequiredError(
                f"Diese Aktion kostet ca. {est.total_cost:.2f} {est.currency} ({est.provider}, {est.count}×). "
                "Bitte ausdrücklich bestätigen und mit dem confirmation_token erneut senden.",
                details={"estimate": est.model_dump()},
            )

    def record(self, est: CostEstimate, job_id: str | None = None) -> None:
        if est.total_cost <= 0:
            return
        self.db.execute(
            "INSERT INTO cost_ledger(created_at,provider,model,operation,count,amount,currency,job_id) VALUES (?,?,?,?,?,?,?,?)",
            (utcnow(), est.provider, est.model, est.operation, est.count, est.total_cost, est.currency, job_id),
        )

    def summary(self) -> dict[str, Any]:
        rows = self.db.fetchall(
            "SELECT provider, COUNT(*) AS n, SUM(amount) AS total FROM cost_ledger GROUP BY provider"
        )
        return {
            "currency": self.currency,
            "monthly_budget": self.monthly_budget,
            "max_cost_per_job": self.max_cost_per_job,
            "spent_this_month": round(self.spent_this_month(), 4),
            "by_provider": {r["provider"]: {"count": r["n"], "total": round(r["total"] or 0, 4)} for r in rows},
        }
