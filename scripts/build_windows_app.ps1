$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AppName = "OBS Code"
$DistDir = Join-Path $RootDir "dist"
$BuildDir = Join-Path $RootDir "build"
$VersionTag = Get-Date -Format "yyyyMMdd-HHmmss"
$IconDir = Join-Path $BuildDir "icon-preview"
$IconPng = Join-Path $IconDir "obs-code-app-icon.png"
$IconIco = Join-Path $BuildDir "obs-code-app-icon.ico"
$ZipPath = Join-Path $DistDir ("OBS-Code-{0}-windows.zip" -f $VersionTag)

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

python -c "import importlib.util; required=['PyInstaller','webview','PIL','clr']; missing=[name for name in required if importlib.util.find_spec(name) is None]; raise SystemExit('Missing required packages: ' + ', '.join(missing) + '. Install pyinstaller pywebview pillow pythonnet first.' if missing else 0)"

if (-not (Test-Path (Join-Path $RootDir "ui\node_modules"))) {
  npm --prefix "$RootDir\ui" install
}
npm --prefix "$RootDir\ui" run build

if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
if (Test-Path $DistDir) { Remove-Item $DistDir -Recurse -Force }
New-Item -ItemType Directory -Path $BuildDir | Out-Null

python "$RootDir\scripts\generate_desktop_icons.py" --png "$IconPng" --ico "$IconIco"

$pyiArgs = @(
  "-m", "PyInstaller",
  "--noconfirm",
  "--windowed",
  "--name", $AppName,
  "--icon", $IconIco,
  "--paths", "$RootDir\src",
  "--paths", "$RootDir\.claude\skills",
  "--hidden-import", "omni_agent.api",
  "--hidden-import", "skill_manager",
  "--hidden-import", "skill_loader",
  "--hidden-import", "base_skill",
  "--hidden-import", "webview",
  "--hidden-import", "clr",
  "--hidden-import", "webview.platforms.winforms",
  "--hidden-import", "webview.platforms.edgechromium",
  "--collect-submodules", "webview.platforms",
  "--collect-all", "webview",
  "--exclude-module", "matplotlib",
  "--exclude-module", "IPython",
  "--exclude-module", "jupyter_client",
  "--exclude-module", "jupyter_core",
  "--exclude-module", "ipykernel",
  "--exclude-module", "pandas",
  "--exclude-module", "scipy"
)

if (Test-Path (Join-Path $RootDir ".env")) {
  $pyiArgs += @("--add-data", "$RootDir\.env;.")
}

$pyiArgs += @(
  "--add-data", "$RootDir\.claude\skills;.claude\skills",
  "--add-data", "$RootDir\frontend;frontend",
  "--add-data", "$RootDir\skills;skills",
  "$RootDir\src\omni_agent\desktop_app.py"
)

python @pyiArgs

$AppDir = Join-Path $DistDir $AppName
if (-not (Test-Path $AppDir)) {
  throw "Windows app directory was not created."
}

Compress-Archive -Path $AppDir -DestinationPath $ZipPath -Force

Write-Output "APP_DIR=$AppDir"
Write-Output "ZIP_PATH=$ZipPath"
