"""Declarative multi-step workflows (``workflows/<category>/*.yaml``).

Example::

    id: images/text-to-image
    name: Text zu Bild
    category: images
    requires: []                 # capabilities: ai_image, ai_video, blender, remotion, rembg, gpu
    fallback: null               # workflow id used when requirements are not met
    inputs:
      prompt: {type: text, required: true}
      variants: {type: integer, default: 2, min: 1, max: 4}
    steps:
      - id: generate
        action: image.generate
        params: {prompt: "{{ inputs.prompt }}", batch_size: "{{ inputs.variants }}"}
      - id: qa
        action: quality.analyze
        when: "{{ inputs.check }}"
        params: {assets: "{{ steps.generate.asset_ids }}"}
    outputs:
      images: "{{ steps.generate.asset_ids }}"

* ``{{ … }}`` expressions run in a Jinja2 *sandbox*. A string that consists of a
  single expression keeps its native type (lists, numbers, dicts).
* ``foreach`` repeats a step for each item (``item``/``index`` in the context); the step output
  then has ``results`` (one entry per item) plus merged ``assets``/``asset_ids``.
* Avoid input names that shadow dict methods in Jinja (``values``, ``items``, ``keys``).
* Actions are Studio operations (``image.generate``, ``process.render`` …) or the
  helper actions defined in ``backend/workflows/actions.py``.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from jinja2 import Undefined
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, ConfigDict, Field

from backend.core.errors import HardwareInsufficientError, NotFoundError, StudioError, ValidationError
from backend.jobs.context import JobContext

from .actions import HELPER_ACTIONS

if TYPE_CHECKING:  # pragma: no cover
    from backend.orchestration.studio import Studio

log = logging.getLogger("workflows")
_SINGLE_EXPR = re.compile(r"^\s*\{\{((?:(?!\}\}|\{\{).)+)\}\}\s*$", re.S)


def _strip_undefined(value: Any) -> Any:
    if isinstance(value, Undefined):
        return None
    if isinstance(value, list):
        return [_strip_undefined(v) for v in value]
    if isinstance(value, tuple):
        return [_strip_undefined(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_undefined(v) for k, v in value.items()}
    return value


class InputSpec(BaseModel):
    type: Literal["string", "text", "integer", "number", "boolean", "list", "object", "asset", "assets", "choice", "color"] = "string"
    required: bool = False
    default: Any = None
    label: str | None = None
    description: str = ""
    options: list[Any] | None = None
    min: float | None = None
    max: float | None = None


class StepSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    action: str
    label: str | None = None
    params: dict[str, Any] = {}
    when: str | None = None
    foreach: str | None = None
    as_: str = Field("item", alias="as")
    continue_on_error: bool = False


class WorkflowSpec(BaseModel):
    id: str
    name: str
    description: str = ""
    category: str = "general"
    tags: list[str] = []
    requires: list[str] = []
    fallback: str | None = None
    inputs: dict[str, InputSpec] = {}
    steps: list[StepSpec]
    outputs: dict[str, Any] = {}
    source: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "description": self.description, "category": self.category,
            "tags": self.tags, "requires": self.requires, "fallback": self.fallback,
            "inputs": {k: v.model_dump() for k, v in self.inputs.items()},
            "steps": [{"id": s.id, "action": s.action, "label": s.label or s.id, "foreach": bool(s.foreach),
                       "conditional": bool(s.when)} for s in self.steps],
        }


class WorkflowEngine:
    def __init__(self, studio: Studio, directory: Path) -> None:
        self.studio = studio
        self.directory = directory
        self.env = SandboxedEnvironment(autoescape=False)
        self.env.filters["slug"] = lambda v: re.sub(r"[^a-z0-9]+", "-", str(v).lower()).strip("-")
        self.specs: dict[str, WorkflowSpec] = {}
        self.reload()

    # ---------------------------------------------------------------- loading
    def reload(self) -> None:
        self.specs.clear()
        if not self.directory.is_dir():
            return
        for path in sorted(self.directory.rglob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            spec = WorkflowSpec(**data, source=str(path.relative_to(self.directory)))
            self._check(spec)
            if spec.id in self.specs:
                raise ValidationError(f"Doppelte Workflow-ID {spec.id}")
            self.specs[spec.id] = spec

    def _check(self, spec: WorkflowSpec) -> None:
        reserved = {"values", "items", "keys", "get", "update", "pop"}
        clash = reserved & set(spec.inputs)
        if clash:
            raise ValidationError(f"Workflow {spec.id}: Eingabenamen {sorted(clash)} kollidieren mit Jinja/dict-Methoden")
        ids = [s.id for s in spec.steps]
        if len(ids) != len(set(ids)):
            raise ValidationError(f"Workflow {spec.id}: doppelte Schritt-IDs")
        known = set(self.studio.ops) | set(HELPER_ACTIONS)
        for step in spec.steps:
            if step.action not in known:
                raise ValidationError(f"Workflow {spec.id}: unbekannte Action '{step.action}' in Schritt {step.id}")

    def list(self) -> list[dict[str, Any]]:
        return [s.public() for s in self.specs.values()]

    def get(self, workflow_id: str) -> WorkflowSpec:
        try:
            return self.specs[workflow_id]
        except KeyError:
            raise NotFoundError(f"Workflow nicht gefunden: {workflow_id}", details={"available": sorted(self.specs)}) from None

    # ----------------------------------------------------------------- inputs
    def coerce_inputs(self, spec: WorkflowSpec, inputs: dict[str, Any]) -> dict[str, Any]:
        unknown = set(inputs) - set(spec.inputs)
        if unknown:
            raise ValidationError(f"Unbekannte Eingaben für {spec.id}: {sorted(unknown)}")
        out: dict[str, Any] = {}
        for name, ispec in spec.inputs.items():
            value = inputs.get(name, ispec.default)
            if value in (None, "") or value == []:
                if ispec.required:
                    raise ValidationError(f"Eingabe '{name}' ist erforderlich")
                out[name] = ispec.default
                continue
            try:
                if ispec.type in ("integer",):
                    value = int(value)
                elif ispec.type == "number":
                    value = float(value)
                elif ispec.type == "boolean":
                    value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "ja", "on")
                elif ispec.type in ("list", "assets") and isinstance(value, str):
                    value = [v.strip() for v in value.split(",") if v.strip()]
                elif ispec.type in ("string", "text", "asset", "color", "choice"):
                    value = str(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"Eingabe '{name}': ungültiger Wert ({exc})") from exc
            if ispec.options and value not in ispec.options:
                raise ValidationError(f"Eingabe '{name}' muss eine von {ispec.options} sein")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if ispec.min is not None and value < ispec.min or ispec.max is not None and value > ispec.max:
                    raise ValidationError(f"Eingabe '{name}' außerhalb des Bereichs [{ispec.min}, {ispec.max}]")
            if ispec.type == "color" and not re.match(r"^#[0-9A-Fa-f]{6}$", value):
                raise ValidationError(f"Eingabe '{name}' muss eine Hex-Farbe sein")
            out[name] = value
        return out

    # -------------------------------------------------------------- templating
    def render_value(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            m = _SINGLE_EXPR.match(value)
            if m:
                return _strip_undefined(self.env.compile_expression(m.group(1).strip(), undefined_to_none=True)(**context))
            if "{{" in value or "{%" in value:
                return self.env.from_string(value).render(**context)
            return value
        if isinstance(value, dict):
            return {k: self.render_value(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [self.render_value(v, context) for v in value]
        return value

    def _truthy(self, expr: str, context: dict[str, Any]) -> bool:
        m = _SINGLE_EXPR.match(expr)
        source = m.group(1) if m else expr
        return bool(self.env.compile_expression(source.strip(), undefined_to_none=True)(**context))

    @staticmethod
    def _clean(params: Any) -> Any:
        """Drop None/empty-string values so optional inputs fall back to defaults."""
        if isinstance(params, dict):
            return {k: WorkflowEngine._clean(v) for k, v in params.items() if v is not None and v != ""}
        if isinstance(params, list):
            return [WorkflowEngine._clean(v) for v in params]
        return params

    # ------------------------------------------------------------------- run
    async def run(self, spec: WorkflowSpec, inputs: dict[str, Any], ctx: JobContext, *, project: str | None = None,
                  confirm_token: str | None = None, _depth: int = 0) -> dict[str, Any]:
        values = self.coerce_inputs(spec, inputs)
        caps = await self.studio.capabilities()
        missing = [r for r in spec.requires if not caps.get(r)]
        if missing:
            if spec.fallback and _depth < 2:
                fb = self.get(spec.fallback)
                log.info("Workflow %s: requirements %s missing → fallback %s", spec.id, missing, fb.id)
                fb_inputs = {k: v for k, v in values.items() if k in fb.inputs and v is not None}
                result = await self.run(fb, fb_inputs, ctx, project=project, confirm_token=confirm_token, _depth=_depth + 1)
                result["fallback_used"] = {"from": spec.id, "to": fb.id, "missing": missing}
                return result
            raise HardwareInsufficientError(
                f"Workflow '{spec.name}' benötigt {', '.join(missing)} – auf diesem System nicht verfügbar.",
                details={"missing": missing, "capabilities": caps},
            )

        context: dict[str, Any] = {"inputs": values, "steps": {}, "caps": caps, "project": project}
        produced: list[dict[str, Any]] = []
        log_entries: list[dict[str, Any]] = []
        n = len(spec.steps)
        for i, step in enumerate(spec.steps):
            ctx.check_cancelled()
            step_ctx = ctx.child(i / n, (i + 1) / n, step.label or step.id)
            started = time.monotonic()
            if step.when and not self._truthy(step.when, context):
                context["steps"][step.id] = {"skipped": True, "assets": [], "asset_ids": [], "asset": None}
                log_entries.append({"step": step.id, "status": "skipped"})
                continue
            try:
                if step.foreach:
                    items = self.render_value("{{ " + step.foreach.strip("{} ") + " }}", context) or []
                    if not isinstance(items, list):
                        raise ValidationError(f"foreach in Schritt {step.id} ergibt keine Liste")
                    results = []
                    for j, item in enumerate(items):
                        sub = step_ctx.child(j / max(1, len(items)), (j + 1) / max(1, len(items)), f"{j + 1}/{len(items)}")
                        local = {**context, step.as_: item, "index": j}
                        results.append(await self._exec(step, local, sub, project, confirm_token))
                    output = {"results": results,
                              "assets": [a for r in results for a in (r.get("assets") or [])],
                              "asset_ids": [a for r in results for a in (r.get("asset_ids") or [])]}
                    output["asset"] = output["assets"][0] if output["assets"] else None
                else:
                    output = await self._exec(step, context, step_ctx, project, confirm_token)
            except StudioError as exc:
                log_entries.append({"step": step.id, "status": "failed", "error": exc.message})
                if not step.continue_on_error:
                    exc.details.setdefault("workflow_step", step.id)
                    exc.message = f"Schritt '{step.label or step.id}' fehlgeschlagen: {exc.message}"
                    raise
                output = {"error": exc.to_dict(), "assets": [], "asset_ids": [], "asset": None}
            context["steps"][step.id] = output
            produced.extend(output.get("assets") or [])
            log_entries.append({"step": step.id, "status": "done", "seconds": round(time.monotonic() - started, 2),
                                "assets": len(output.get("asset_ids") or [])})
        outputs = self.render_value(spec.outputs, context) if spec.outputs else {}
        unique = {a["id"]: a for a in produced if isinstance(a, dict) and a.get("id")}
        return {
            "workflow_id": spec.id,
            "outputs": outputs,
            "assets": list(unique.values()),
            "asset_ids": list(unique),
            "steps": {k: self._summarize(v) for k, v in context["steps"].items()},
            "log": log_entries,
        }

    async def _exec(self, step: StepSpec, context: dict[str, Any], ctx: JobContext, project: str | None,
                    confirm_token: str | None) -> dict[str, Any]:
        params = self._clean(self.render_value(step.params, context))
        if project and "project" not in params and step.action in self.studio.ops:
            params["project"] = project
        if step.action in HELPER_ACTIONS:
            return await HELPER_ACTIONS[step.action](self.studio, params, ctx)
        if confirm_token and params.get("provider"):
            params["confirm_token"] = confirm_token
        return await self.studio.run_op(step.action, params, ctx)

    @staticmethod
    def _summarize(output: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in output.items() if k not in ("assets", "results", "asset")}
        if output.get("results") is not None:
            out["results"] = [WorkflowEngine._summarize(i) for i in output["results"]]
        return out
