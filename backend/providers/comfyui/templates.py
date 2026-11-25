"""ComfyUI workflow templates (API format + parameter mapping).

Template file layout (``engines/comfyui/workflows/<id>.json``)::

    {
      "meta": {
        "id": "checkpoint_txt2img",
        "name": "…", "task": "text_to_image", "kind": "image",
        "description": "…",
        "parameters": {
          "prompt": {"targets": [["6", "text"]], "required": true},
          "width":  {"targets": [["5", "width"]], "default": 1024},
          …
        },
        "uploads": ["image"],                 # parameters that are local files to upload
        "lora_anchor": {"model": ["4", 0], "clip": ["4", 1]},   # optional
        "outputs": ["9"]
      },
      "workflow": { "<node_id>": {"class_type": "…", "inputs": {…}}, … }
    }

You can add your own workflow: export it from ComfyUI with *Save (API Format)*,
wrap it like above and drop it into the folder.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.core.errors import NotFoundError, ValidationError


class ParamSpec(BaseModel):
    targets: list[tuple[str, str]]
    default: Any = None
    required: bool = False
    description: str = ""


class TemplateMeta(BaseModel):
    id: str
    name: str
    task: str
    kind: str = "image"
    description: str = ""
    family: str | None = None
    parameters: dict[str, ParamSpec] = {}
    uploads: list[str] = []
    lora_anchor: dict[str, tuple[str, int]] | None = None
    outputs: list[str] = []
    requires_custom_nodes: list[str] = Field(default_factory=list)


class ComfyTemplate(BaseModel):
    meta: TemplateMeta
    workflow: dict[str, dict[str, Any]]
    source: str | None = None

    @property
    def id(self) -> str:
        return self.meta.id

    def structural_errors(self) -> list[str]:
        errors: list[str] = []
        for node_id, node in self.workflow.items():
            if "class_type" not in node or "inputs" not in node:
                errors.append(f"node {node_id}: missing class_type/inputs")
                continue
            for name, value in node["inputs"].items():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                    if value[0] not in self.workflow:
                        errors.append(f"node {node_id}.{name}: link to missing node {value[0]}")
        for pname, spec in self.meta.parameters.items():
            for node_id, input_name in spec.targets:
                node = self.workflow.get(node_id)
                if node is None:
                    errors.append(f"parameter {pname}: target node {node_id} missing")
                elif input_name not in node.get("inputs", {}):
                    errors.append(f"parameter {pname}: input {node_id}.{input_name} missing")
        for out in self.meta.outputs:
            if out not in self.workflow:
                errors.append(f"output node {out} missing")
        if self.meta.lora_anchor:
            for key in ("model", "clip"):
                ref = self.meta.lora_anchor.get(key)
                if ref and ref[0] not in self.workflow:
                    errors.append(f"lora_anchor.{key} references missing node {ref[0]}")
        return errors

    def validate_object_info(self, object_info: dict[str, Any], *, check_enums: bool = True) -> list[str]:
        """Check node classes, input names and (non-model) enum values against ComfyUI's /object_info."""
        errors: list[str] = []
        for node_id, node in self.workflow.items():
            cls = node.get("class_type")
            spec = object_info.get(cls)
            if spec is None:
                errors.append(f"node {node_id}: unknown node class '{cls}'")
                continue
            declared = {**spec.get("input", {}).get("required", {}), **spec.get("input", {}).get("optional", {})}
            for name, value in node.get("inputs", {}).items():
                base = name.split(".", 1)[0]
                if base not in declared:
                    errors.append(f"node {node_id} ({cls}): unknown input '{name}'")
                    continue
                if not check_enums or (isinstance(value, list)):
                    continue
                type_def = declared[base][0]
                options = None
                if isinstance(type_def, list):
                    options = type_def
                elif type_def == "COMBO" and len(declared[base]) > 1 and isinstance(declared[base][1], dict):
                    options = declared[base][1].get("options")
                # Model file lists depend on installed files → skip those.
                if options and name not in {"ckpt_name", "unet_name", "clip_name", "vae_name", "lora_name",
                                            "model_name", "image"} and value not in options:
                    errors.append(f"node {node_id} ({cls}).{name}: '{value}' not in {options[:8]}…")
            for req_name in spec.get("input", {}).get("required", {}):
                if req_name not in node.get("inputs", {}):
                    errors.append(f"node {node_id} ({cls}): missing required input '{req_name}'")
        return errors


class TemplateLibrary:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.templates: dict[str, ComfyTemplate] = {}
        self.reload()

    def reload(self) -> None:
        self.templates.clear()
        if not self.directory.is_dir():
            return
        for path in sorted(self.directory.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            tpl = ComfyTemplate(meta=TemplateMeta(**data["meta"]), workflow=data["workflow"], source=str(path))
            errors = tpl.structural_errors()
            if errors:
                raise ValidationError(f"Invalid ComfyUI template {path.name}: {errors}")
            self.templates[tpl.id] = tpl

    def get(self, template_id: str) -> ComfyTemplate:
        try:
            return self.templates[template_id]
        except KeyError:
            raise NotFoundError(f"Unknown ComfyUI template '{template_id}'",
                                details={"available": sorted(self.templates)}) from None

    def list(self, task: str | None = None) -> list[ComfyTemplate]:
        return [t for t in self.templates.values() if task is None or t.meta.task == task]


def render(template: ComfyTemplate, values: dict[str, Any]) -> dict[str, Any]:
    """Return a new workflow with all parameter values applied."""
    workflow = copy.deepcopy(template.workflow)
    unknown = set(values) - set(template.meta.parameters)
    if unknown:
        raise ValidationError(f"Template '{template.id}' has no parameters {sorted(unknown)}",
                              details={"parameters": sorted(template.meta.parameters)})
    for name, spec in template.meta.parameters.items():
        value = values.get(name, spec.default)
        if value is None:
            if spec.required:
                raise ValidationError(f"Template '{template.id}': parameter '{name}' is required")
            continue
        for node_id, input_name in spec.targets:
            workflow[node_id]["inputs"][input_name] = value
    return workflow


def insert_loras(workflow: dict[str, Any], anchor: dict[str, tuple[str, int]] | None,
                 loras: list[dict[str, Any]]) -> dict[str, Any]:
    """Insert a chain of LoraLoader nodes after the model/clip anchor and rewire consumers."""
    if not loras:
        return workflow
    if not anchor:
        raise ValidationError("This workflow template does not support LoRAs")
    model_ref = list(anchor["model"])
    clip_ref = list(anchor["clip"])
    next_id = max(int(k) for k in workflow if k.isdigit()) + 1
    cur_model, cur_clip = model_ref, clip_ref
    new_nodes: dict[str, Any] = {}
    for lora in loras:
        node_id = str(next_id)
        next_id += 1
        new_nodes[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": cur_model, "clip": cur_clip, "lora_name": lora["name"],
                "strength_model": float(lora.get("strength", 1.0)), "strength_clip": float(lora.get("strength", 1.0)),
            },
        }
        cur_model, cur_clip = [node_id, 0], [node_id, 1]
    for node in workflow.values():
        for key, value in node["inputs"].items():
            if value == model_ref:
                node["inputs"][key] = cur_model
            elif value == clip_ref:
                node["inputs"][key] = cur_clip
    workflow.update(new_nodes)
    return workflow
