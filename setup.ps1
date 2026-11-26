<#
.SYNOPSIS
  AI Creative Studio – Setup für Windows (PowerShell 5.1+).

.DESCRIPTION
  Idempotent: fügt nur Fehlendes hinzu, überschreibt keine bestehende Konfiguration
  (.env, configs\*.local.yaml). Große Downloads (ComfyUI + PyTorch, Modelle) werden
  einzeln bestätigt.

.PARAMETER Yes          Kleine/sichere Schritte ohne Rückfrage (lädt NIE Modelle).
.PARAMETER SkipComfyUI  ComfyUI nicht installieren (eigene Instanz: ACS__COMFYUI__URL in .env).
.PARAMETER SkipNode     Dashboard-Build und Remotion überspringen.
.PARAMETER Cpu          CPU-PyTorch für ComfyUI installieren.
.PARAMETER WithModels   Am Ende empfohlene Modelle anbieten.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\setup.ps1
#>
[CmdletBinding()]
param(
  [switch]$Yes,
  [switch]$SkipComfyUI,
  [switch]$SkipNode,
  [switch]$Cpu,
  [switch]$WithModels
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Err($m)  { Write-Host "  [X]  $m" -ForegroundColor Red }
function Step($m) { Write-Host "`n== $m ==" -ForegroundColor Cyan }
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Ask($q, $default = "n") {
  if ($Yes) { return $default -eq "y" }
  $hint = if ($default -eq "y") { "[J/n]" } else { "[j/N]" }
  $r = Read-Host "$q $hint"
  if ([string]::IsNullOrWhiteSpace($r)) { $r = $default }
  return $r -match '^(j|ja|y|yes)$'
}
function Run($exe, [string[]]$argList) {
  & $exe @argList
  if ($LASTEXITCODE -ne 0) { throw "Befehl fehlgeschlagen ($LASTEXITCODE): $exe $($argList -join ' ')" }
}

# ------------------------------------------------------------ 1. prerequisites
Step "1/8 Voraussetzungen"
$Py = $null
foreach ($cand in @(@("py", "-3"), @("python"), @("python3"))) {
  if (Have $cand[0]) {
    $args0 = @()
    if ($cand.Count -gt 1) { $args0 = $cand[1..($cand.Count - 1)] }
    & $cand[0] @args0 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $Py = $cand; break }
  }
}
$HaveUv = Have "uv"
if (-not $Py -and -not $HaveUv) {
  Err "Python >= 3.10 nicht gefunden."
  if ((Have "winget") -and (Ask "Python 3.12 mit winget installieren?" "y")) {
    Run "winget" @("install", "-e", "--id", "Python.Python.3.12", "--accept-package-agreements", "--accept-source-agreements")
    Warn "Bitte ein neues PowerShell-Fenster öffnen und setup.ps1 erneut starten."
  }
  exit 1
}
if ($Py) { Ok ("Python: " + (& $Py[0] @($Py | Select-Object -Skip 1) --version 2>&1)) }
if ($HaveUv) { Ok ("uv: " + (uv --version)) }
if (Have "git") { Ok (git --version) } else {
  Warn "git fehlt (für ComfyUI nötig)."
  if ((Have "winget") -and (Ask "Git mit winget installieren?" "y")) { Run "winget" @("install", "-e", "--id", "Git.Git", "--accept-package-agreements", "--accept-source-agreements") }
}
if ((Have "ffmpeg") -and (Have "ffprobe")) { Ok ("FFmpeg: " + ((ffmpeg -version | Select-Object -First 1) -split ' ')[2]) } else {
  Warn "FFmpeg fehlt (Pflicht für Videoverarbeitung)."
  if ((Have "winget") -and (Ask "FFmpeg mit winget installieren (Gyan.FFmpeg)?" "y")) {
    Run "winget" @("install", "-e", "--id", "Gyan.FFmpeg", "--accept-package-agreements", "--accept-source-agreements")
    Warn "Nach der Installation ein neues Terminal öffnen (PATH)."
  } else { Warn "Manuell: https://ffmpeg.org/download.html" }
}
$NodeOk = $false
if (Have "node") {
  $major = [int]((node --version).TrimStart('v').Split('.')[0])
  if ($major -ge 20) { $NodeOk = $true; Ok ("Node.js: " + (node --version)) }
}
if (-not $NodeOk) {
  Warn "Node.js >= 20 fehlt – Dashboard-Build und Remotion werden übersprungen."
  if ((Have "winget") -and (Ask "Node.js LTS mit winget installieren?" "n")) { Run "winget" @("install", "-e", "--id", "OpenJS.NodeJS.LTS", "--accept-package-agreements", "--accept-source-agreements") }
}
if (Have "blender") { Ok "Blender gefunden" } else { Warn "Blender nicht gefunden – 3D optional (blender.org; Pfad ggf. via ACS__BLENDER__BLENDER_PATH)." }

# ------------------------------------------------------------ 2. python env
Step "2/8 Python-Umgebung (.venv)"
$VPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VPy)) {
  if ($HaveUv) { Run "uv" @("venv", "--python", ">=3.10", ".venv") }
  else { & $Py[0] @($Py | Select-Object -Skip 1) -m venv .venv; if ($LASTEXITCODE -ne 0) { throw "venv fehlgeschlagen" } }
  Ok ".venv erstellt"
} else { Ok ".venv vorhanden" }
if ($HaveUv) { $env:VIRTUAL_ENV = Join-Path $Root ".venv"; Run "uv" @("pip", "install", "-q", "-e", ".[dev]") }
else { Run $VPy @("-m", "pip", "install", "-q", "--upgrade", "pip"); Run $VPy @("-m", "pip", "install", "-q", "-e", ".[dev]") }
Ok "Python-Abhängigkeiten installiert"
& $VPy -c "import rembg" 2>$null
if ($LASTEXITCODE -ne 0 -and (Ask "Optional: Hintergrundentfernung (rembg, ~200 MB) installieren?" "n")) {
  if ($HaveUv) { Run "uv" @("pip", "install", "-q", "-e", ".[rembg]") } else { Run $VPy @("-m", "pip", "install", "-q", "-e", ".[rembg]") }
}

# MCP: .mcp.json nutzt ${ACS_PYTHON:-.venv/bin/python}; unter Windows ACS_PYTHON setzen.
$current = [Environment]::GetEnvironmentVariable("ACS_PYTHON", "User")
if ($current -ne $VPy) {
  if (Ask "Benutzer-Umgebungsvariable ACS_PYTHON=$VPy setzen (nötig für den MCP-Server in Claude Code)?" "y") {
    [Environment]::SetEnvironmentVariable("ACS_PYTHON", $VPy, "User")
    $env:ACS_PYTHON = $VPy
    Ok "ACS_PYTHON gesetzt (neue Terminals/Claude-Code-Sitzungen übernehmen sie)"
  } else { Warn "Ohne ACS_PYTHON findet Claude Code den MCP-Server unter Windows nicht." }
} else { Ok "ACS_PYTHON bereits gesetzt" }

# ------------------------------------------------------------ 3. config
Step "3/8 Konfiguration"
if (Test-Path ".env") { Ok ".env vorhanden (unverändert)" } else { Copy-Item ".env.example" ".env"; Ok ".env erstellt" }
Run $VPy @("-c", "from backend.core.config import load_settings; s=load_settings(); s.ensure_dirs(); print('  [OK] Verzeichnisse bereit')")

# ------------------------------------------------------------ 4. hardware
Step "4/8 Hardware-Analyse"
& $VPy -m backend.cli hardware --write-report | Select-Object -First 14
$Accel = & $VPy -c "import json,subprocess,sys; from backend.core.hardware import collect_report, select_profile; r=collect_report(); print(select_profile(r).accelerator)"
Ok "Report: data\reports\hardware-report.md (Beschleuniger: $Accel)"

# ------------------------------------------------------------ 5. ComfyUI
Step "5/8 ComfyUI"
$ComfyDir = & $VPy -c "from backend.core.config import load_settings as l; s=l(); print(s.resolve(s.paths.comfyui_dir))"
if ($SkipComfyUI) { Warn "übersprungen – eigene Instanz: ACS__COMFYUI__URL in .env" }
elseif (Test-Path (Join-Path $ComfyDir "main.py")) {
  Ok "ComfyUI vorhanden: $ComfyDir"
  if ((Test-Path (Join-Path $ComfyDir ".git")) -and (Ask "ComfyUI aktualisieren (git pull + requirements)?" "n")) {
    Run "git" @("-C", $ComfyDir, "pull", "--ff-only")
    Run (Join-Path $ComfyDir ".venv\Scripts\python.exe") @("-m", "pip", "install", "-q", "-r", (Join-Path $ComfyDir "requirements.txt"))
  }
} else {
  $torchArgs = (& $VPy scripts\setup\torch_index.py $(if ($Cpu) { "--cpu" })).Trim().Split(" ")
  Write-Host "  ComfyUI wird nach $ComfyDir installiert (git clone + eigenes venv)."
  Write-Host "  PyTorch: pip install $($torchArgs -join ' ')  (ca. 1–4 GB, ohne Modelle)"
  Write-Host "  Alternative: ComfyUI Desktop (https://www.comfy.org/download) und ACS__COMFYUI__URL setzen."
  if (Ask "ComfyUI jetzt installieren?" "y") {
    Run "git" @("clone", "--depth", "1", "https://github.com/Comfy-Org/ComfyUI.git", $ComfyDir)
    $CVenv = Join-Path $ComfyDir ".venv"
    if ($HaveUv) { Run "uv" @("venv", "--python", ">=3.10", $CVenv) } else { & $Py[0] @($Py | Select-Object -Skip 1) -m venv $CVenv }
    $CPy = Join-Path $CVenv "Scripts\python.exe"
    if ($HaveUv) {
      $env:VIRTUAL_ENV = $CVenv
      Run "uv" (@("pip", "install") + $torchArgs)
      Run "uv" @("pip", "install", "-r", (Join-Path $ComfyDir "requirements.txt"))
      $env:VIRTUAL_ENV = Join-Path $Root ".venv"
    } else {
      Run $CPy (@("-m", "pip", "install") + $torchArgs)
      Run $CPy @("-m", "pip", "install", "-r", (Join-Path $ComfyDir "requirements.txt"))
    }
    Ok "ComfyUI installiert"
  } else { Warn "ComfyUI nicht installiert – Generierung erst danach verfügbar." }
}

# ------------------------------------------------------------ 6. node
Step "6/8 Dashboard & Remotion"
if ($SkipNode -or -not $NodeOk) { Warn "übersprungen" } else {
  Push-Location apps\dashboard
  try { Run "npm" @("install", "--no-fund", "--no-audit", "--loglevel=error"); Run "npm" @("run", "build", "--silent"); Ok "Dashboard gebaut" } finally { Pop-Location }
  if (Test-Path "engines\remotion\node_modules\@remotion\cli") { Ok "Remotion vorhanden" }
  elseif (Ask "Remotion installieren? ~300 MB inkl. Headless-Chrome. Lizenz: kostenlos für Einzelpersonen/Firmen <= 3 Personen." "y") {
    Push-Location engines\remotion
    try { Run "npm" @("install", "--no-fund", "--no-audit", "--loglevel=error"); Run "npx" @("remotion", "browser", "ensure"); Ok "Remotion bereit" } finally { Pop-Location }
  }
}

# ------------------------------------------------------------ 7. claude
Step "7/8 Claude Code"
Ok ".mcp.json registriert den MCP-Server 'ai-creative-studio' (Python über ACS_PYTHON)"
Ok "$((Get-ChildItem .claude\agents -Filter *.md).Count) Agents, $((Get-ChildItem .claude\skills -Directory).Count) Skills"

# ------------------------------------------------------------ 8. verify
Step "8/8 Überprüfung"
& $VPy -m backend.cli check
if (Ask "Kurzen Testlauf (Unit-Tests, ~1 Minute) ausführen?" "n") { & $VPy -m pytest -q -x tests\unit }
if ($WithModels -or (Ask "Empfohlene Modelle anzeigen/herunterladen (jede Datei einzeln bestätigt)?" "n")) {
  & $VPy scripts\models\download_models.py --recommended --comfyui-dir $ComfyDir
} else { Write-Host "  Modelle später: .venv\Scripts\python.exe scripts\models\download_models.py --list" }
Write-Host "`nFertig. Starten mit: .\start.ps1  ->  http://127.0.0.1:8420" -ForegroundColor Green
