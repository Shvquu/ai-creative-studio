<#
.SYNOPSIS
  AI Creative Studio - Systempruefung fuer Windows. Funktioniert vor und nach dem Setup.
#>
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
# Windows PowerShell 5.1 reads scripts as ANSI and Python uses the console code page when piped:
# keep this file ASCII-only and force UTF-8 for Python output.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
function Row($k, $v) { Write-Host ("  {0,-14} {1}" -f $k, $v) }
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

Write-Host "== System =="
$os = Get-CimInstance Win32_OperatingSystem
Row "OS" "$($os.Caption) $($os.Version) ($env:PROCESSOR_ARCHITECTURE)"
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
Row "CPU" "$($cpu.Name.Trim()) ($($cpu.NumberOfCores) Kerne / $($cpu.NumberOfLogicalProcessors) Threads)"
Row "RAM" ("{0:N1} GB" -f ($os.TotalVisibleMemorySize / 1MB))
$drive = (Get-Item $Root).PSDrive
Row "Speicher" ("{0:N0} GB frei" -f ($drive.Free / 1GB))
if (Have "nvidia-smi") {
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | ForEach-Object { Row "GPU (NVIDIA)" $_ }
  $cuda = (nvidia-smi | Select-String -Pattern "CUDA Version: ([0-9.]+)").Matches | Select-Object -First 1
  if ($cuda) { Row "CUDA" $cuda.Groups[1].Value }
} else {
  Get-CimInstance Win32_VideoController | ForEach-Object { Row "GPU" "$($_.Name) (kein CUDA - AMD/Intel nur via DirectML, langsamer)" }
}

Write-Host "`n== Werkzeuge =="
foreach ($t in @("python", "py", "git", "ffmpeg", "ffprobe", "node", "npm", "blender", "uv", "docker")) {
  if (Have $t) {
    $v = (& $t --version 2>&1 | Select-Object -First 1) -as [string]
    if ($v.Length -gt 70) { $v = $v.Substring(0, 70) }
    Row $t $v
  } else { Row $t "- nicht gefunden" }
}

$VPy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VPy) {
  Write-Host "`n== Hardwareprofil & Empfehlungen =="
  & $VPy -m backend.cli hardware --write-report | Select-Object -Skip 4 -First 36
  Write-Host "`n== Provider =="
  & $VPy -m backend.cli check
  Write-Host "`nReport gespeichert: data\reports\hardware-report.md"
} else {
  Write-Host "`nNoch nicht eingerichtet -> .\setup.ps1 ausfuehren."
}
