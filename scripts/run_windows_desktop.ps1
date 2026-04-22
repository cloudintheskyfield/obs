$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RootDir

if (Test-Path (Join-Path $RootDir ".env")) {
  Get-Content (Join-Path $RootDir ".env") | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
      [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2], "Process")
    }
  }
}

$env:PYTHONPATH = Join-Path $RootDir "src"
if (-not $env:SKILLS_DIR) {
  $env:SKILLS_DIR = Join-Path $RootDir ".claude\skills"
}
if (-not $env:OBS_DESKTOP_MIRROR_WEB) {
  $env:OBS_DESKTOP_MIRROR_WEB = "1"
}
if (-not $env:OBS_DESKTOP_GUI) {
  $env:OBS_DESKTOP_GUI = "edgechromium"
}

if (-not $env:OBS_DESKTOP_TARGET_URL -and $env:OBS_WEB_URL) {
  $env:OBS_DESKTOP_TARGET_URL = $env:OBS_WEB_URL
}

if (-not $env:OBS_DESKTOP_TARGET_URL) {
  try {
    $health = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2 -UseBasicParsing
    if ($health.StatusCode -eq 200) {
      $env:OBS_DESKTOP_TARGET_URL = "http://127.0.0.1:8000"
    }
  } catch {
  }
}

if (-not $env:OBS_DESKTOP_TARGET_URL) {
  if (-not (Test-Path (Join-Path $RootDir "ui\node_modules"))) {
    npm --prefix "$RootDir\ui" install
  }
  npm --prefix "$RootDir\ui" run build
}

python -m omni_agent.main desktop
