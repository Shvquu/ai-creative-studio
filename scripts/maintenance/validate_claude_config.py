"""Validate .claude/agents and .claude/skills: frontmatter, MCP tool names, workflow ids and model ids.

Usage: python scripts/maintenance/validate_claude_config.py [repo-root]
"""

import re
import sys
from pathlib import Path

import yaml

root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[2])
sys.path.insert(0, str(root.resolve()))
import asyncio  # noqa: E402

from mcp_server.server import mcp  # noqa: E402

TOOLS = {t.name for t in asyncio.run(mcp.list_tools())}
WORKFLOWS = {yaml.safe_load(p.read_text())["id"] for p in (root / "workflows").rglob("*.yaml")}
CAT = yaml.safe_load((root / "configs/models.yaml").read_text())["models"]
MODELS = {m["id"] for m in CAT}
FAMILIES = {m["family"] for m in CAT}
CLAUDE_TOOLS = {"Read", "Glob", "Grep", "Write", "Edit", "Bash"}
problems = []
files = sorted((root / ".claude/agents").glob("*.md")) + sorted((root / ".claude/skills").glob("*/SKILL.md"))
for f in files:
    text = f.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        problems.append(f"{f}: no frontmatter")
        continue
    fm = yaml.safe_load(m.group(1))
    for key in ("name", "description"):
        if not fm.get(key):
            problems.append(f"{f}: missing {key}")
    expected = f.stem if f.parent.name == "agents" else f.parent.name
    if fm.get("name") != expected:
        problems.append(f"{f}: name {fm.get('name')} != {expected}")
    if len(fm.get("description", "")) > 1024:
        problems.append(f"{f}: description {len(fm['description'])} chars")
    if f.parent.name == "agents":
        for t in [t.strip() for t in fm.get("tools", "").split(",") if t.strip()]:
            if t.startswith("mcp__ai-creative-studio__"):
                if t.split("__")[-1] not in TOOLS:
                    problems.append(f"{f}: unknown tool in frontmatter {t}")
            elif t not in CLAUDE_TOOLS:
                problems.append(f"{f}: unknown tool {t}")
    body = text[m.end() :]
    for t in re.findall(r"mcp__ai-creative-studio__(\w+)", body):
        if t not in TOOLS:
            problems.append(f"{f}: unknown tool {t}")
    for call in re.findall(r"(?<![\w./])([a-z][a-z0-9_]+)\(", body):
        if "_" in call and call not in TOOLS and call not in {"ken_burns", "prompt_build"}:
            problems.append(f"{f}: call to unknown function {call}(")
    for wf in re.findall(
        r"(?<!api/)(?<![\w/])((?:images|videos|branding|social-media|motion-design)/[a-z0-9-]+)\b",
        body + fm.get("description", ""),
    ):
        if wf not in WORKFLOWS:
            problems.append(f"{f}: unknown workflow {wf}")
    for mid in re.findall(r"`([a-z0-9][a-z0-9.-]+)`", body):
        if (
            re.match(r"^(sd15|sdxl|flux|z-image|wan2|realesrgan)", mid)
            and mid not in MODELS
            and mid not in FAMILIES
            and not mid.endswith(".safetensors")
        ):
            problems.append(f"{f}: unknown model id {mid}")
print(f"checked {len(files)} files, {len(WORKFLOWS)} workflows, {len(MODELS)} models")
print("\n".join(problems) or "NO PROBLEMS")
