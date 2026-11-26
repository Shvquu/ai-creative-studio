"""Setup/start scripts: guard against Windows PowerShell 5.1 pitfalls and shell syntax errors.

Windows PowerShell 5.1 reads .ps1 files without BOM as ANSI (cp1252). UTF-8 punctuation such as an
en dash (E2 80 93) then turns into characters PowerShell treats as quotes, breaking the parser.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PS_SCRIPTS = sorted(REPO.glob("*.ps1"))
SH_SCRIPTS = sorted(REPO.glob("*.sh"))


def test_scripts_exist() -> None:
    names = {p.name for p in PS_SCRIPTS + SH_SCRIPTS}
    assert {"setup.ps1", "start.ps1", "check-system.ps1", "setup.sh", "start.sh", "check-system.sh"} <= names


@pytest.mark.parametrize("script", PS_SCRIPTS, ids=lambda p: p.name)
def test_powershell_scripts_are_ascii(script: Path) -> None:
    bad = sorted({(i + 1, ch) for i, line in enumerate(script.read_text(encoding="utf-8").splitlines())
                  for ch in line if ord(ch) > 127})
    assert not bad, f"non-ASCII characters break Windows PowerShell 5.1: {bad[:10]}"


@pytest.mark.parametrize("script", PS_SCRIPTS, ids=lambda p: p.name)
def test_no_stderr_redirect_with_stop_preference(script: Path) -> None:
    """With $ErrorActionPreference='Stop', 2>$null / 2>&1 on native commands throws in PS 5.1."""
    text = script.read_text(encoding="utf-8")
    if '$ErrorActionPreference = "Stop"' not in text:
        return
    offending = [line.strip() for line in text.splitlines()
                 if re.search(r"2>(\$null|&1)", line) and not line.lstrip().startswith("#")
                 and "Out-Null; return $LASTEXITCODE" not in line]
    assert not offending, offending


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell (pwsh) not installed")
@pytest.mark.parametrize("script", PS_SCRIPTS, ids=lambda p: p.name)
def test_powershell_parses_as_ps51_reads_it(script: Path, tmp_path: Path) -> None:
    raw = script.read_bytes()
    text = raw[3:].decode("utf-8") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("cp1252", errors="replace")
    sim = tmp_path / script.name
    sim.write_text(text, encoding="utf-8-sig")
    cmd = ("$e=$null; $t=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
           f"'{sim}',[ref]$t,[ref]$e); $e | ForEach-Object {{ $_.Message + ' @' + $_.Extent.StartLineNumber }}")
    out = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "", out.stdout


@pytest.mark.parametrize("script", SH_SCRIPTS, ids=lambda p: p.name)
def test_shell_scripts_syntax(script: Path) -> None:
    assert script.read_bytes().count(b"\r\n") == 0, "CRLF line endings break bash"
    out = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
