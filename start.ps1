<#
.SYNOPSIS
  AI Creative Studio starten (ComfyUI falls lokal installiert + Backend/Dashboard).
.PARAMETER NoComfyUI  ComfyUI nicht starten (bereits laufende Instanz nutzen).
.PARAMETER Dev        Zusaetzlich den Dashboard-Dev-Server (Vite, Port 5173) starten.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\start.ps1
#>
[CmdletBinding()]
param([switch]$NoComfyUI, [switch]$Dev, [string]$HostName = "", [int]$Port = 0)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
# Windows PowerShell 5.1 reads scripts as ANSI and Python uses the console code page when piped:
# keep this file ASCII-only and force UTF-8 for Python output.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$VPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VPy)) { Write-Host "Nicht eingerichtet - zuerst .\setup.ps1 ausfuehren." -ForegroundColor Red; exit 1 }
New-Item -ItemType Directory -Force -Path (Join-Path $Root "data\logs") | Out-Null

$info = (& $VPy -c "from backend.core.config import load_settings as l; s=l(); print(s.comfyui.url); print(s.resolve(s.paths.comfyui_dir))") -split "`r?`n"
$ComfyUrl = $info[0].Trim(); $ComfyDir = $info[1].Trim()
$ComfyPort = ([Uri]$ComfyUrl).Port
$procs = @()

function Test-Comfy {
  try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "$ComfyUrl/system_stats" | Out-Null; return $true } catch { return $false }
}

try {
  if (-not $NoComfyUI) {
    if (Test-Comfy) { Write-Host "[OK] ComfyUI laeuft bereits ($ComfyUrl)" -ForegroundColor Green }
    elseif ((Test-Path (Join-Path $ComfyDir "main.py")) -and (Test-Path (Join-Path $ComfyDir ".venv\Scripts\python.exe"))) {
      $extra = (& $VPy scripts\setup\comfyui_args.py).Trim()
      $argList = @("main.py", "--listen", "127.0.0.1", "--port", "$ComfyPort")
      if ($extra) { $argList += $extra.Split(" ") }
      Write-Host "-> starte ComfyUI ($ComfyDir) - Log: data\logs\comfyui.log"
      $p = Start-Process -FilePath (Join-Path $ComfyDir ".venv\Scripts\python.exe") -ArgumentList $argList -WorkingDirectory $ComfyDir `
        -RedirectStandardOutput (Join-Path $Root "data\logs\comfyui.log") -RedirectStandardError (Join-Path $Root "data\logs\comfyui.err.log") `
        -WindowStyle Hidden -PassThru
      $procs += $p
      for ($i = 0; $i -lt 90; $i++) { if (Test-Comfy) { Write-Host "[OK] ComfyUI bereit" -ForegroundColor Green; break }; Start-Sleep -Seconds 1 }
    } else {
      Write-Host "[!] ComfyUI nicht installiert/erreichbar - Generierung nicht verfuegbar (Verarbeitung schon)." -ForegroundColor Yellow
    }
  }
  if ($Dev) {
    $procs += Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") -WorkingDirectory (Join-Path $Root "apps\dashboard") -WindowStyle Hidden -PassThru
    Write-Host "-> Dashboard-Dev-Server: http://127.0.0.1:5173"
  }
  $serveArgs = @("-m", "backend.cli", "serve")
  if ($HostName) { $serveArgs += @("--host", $HostName) }
  if ($Port -gt 0) { $serveArgs += @("--port", "$Port") }
  $shownHost = if ($HostName) { $HostName } else { "127.0.0.1" }
  $shownPort = if ($Port -gt 0) { $Port } else { 8420 }
  Write-Host "-> Backend & Dashboard: http://$($shownHost):$shownPort  (Strg+C beendet alles)" -ForegroundColor Cyan
  & $VPy @serveArgs
} finally {
  foreach ($p in $procs) { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }
}
