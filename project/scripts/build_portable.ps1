$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$buildRoot = Join-Path $root "project\build"
$workPath = Join-Path $buildRoot "pyinstaller-work"
$pyiDistPath = Join-Path $buildRoot "pyinstaller-dist"
$portablePath = Join-Path $root "project\dist\NetConsolePortable"

Write-Host "Cleaning PyInstaller temporary directories..."
Remove-Item -LiteralPath $workPath -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pyiDistPath -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $portablePath -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Building NetConsole.exe with PyInstaller..."
& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name NetConsole `
    --workpath $workPath `
    --distpath $pyiDistPath `
    --specpath $buildRoot `
    --hidden-import PySide6.QtCore `
    --hidden-import PySide6.QtGui `
    --hidden-import PySide6.QtWidgets `
    main.py

$builtApp = Join-Path $pyiDistPath "NetConsole"
$builtExe = Join-Path $builtApp "NetConsole.exe"
if (-not (Test-Path $builtExe)) {
    throw "PyInstaller did not produce NetConsole.exe at $builtExe"
}

Write-Host "Creating portable output..."
New-Item -ItemType Directory -Force -Path $portablePath | Out-Null
Copy-Item -Path (Join-Path $builtApp "*") -Destination $portablePath -Recurse -Force

foreach ($blockedDir in @("tests", ".venv", "__pycache__", ".pytest_cache")) {
    Get-ChildItem -Path $portablePath -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $blockedDir } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
}

foreach ($dir in @("data", "docs")) {
    $source = Join-Path $root $dir
    if (Test-Path $source) {
        Copy-Item -Path $source -Destination (Join-Path $portablePath $dir) -Recurse -Force
    } else {
        New-Item -ItemType Directory -Force -Path (Join-Path $portablePath $dir) | Out-Null
    }
}

$projectOutput = Join-Path $portablePath "project"
$resourcesOutput = Join-Path $projectOutput "resources"
New-Item -ItemType Directory -Force -Path $resourcesOutput | Out-Null
$resourcesSource = Join-Path $root "project\resources"
if (Test-Path $resourcesSource) {
    Copy-Item -Path (Join-Path $resourcesSource "*") -Destination $resourcesOutput -Recurse -Force
}

$readmeRun = @(
    "NetConsole Windows Portable",
    "",
    "How to start",
    "1. Extract NetConsolePortable to a local Windows Server directory.",
    "2. Run NetConsole.exe directly.",
    "3. If security software blocks the app, allow or trust NetConsole.exe first.",
    "",
    "Data directory",
    "- All runtime data is written to the data directory next to NetConsole.exe.",
    "- Application log: data\logs\app.log",
    "- Demo database: data\sites\demo\db\devices.db",
    "- Raw collection logs: data\sites\demo\raw\collect and data\sites\demo\raw\ac",
    "",
    "Demo data",
    "- The demo site is checked and created on startup.",
    "- To rebuild demo data, delete data\sites\demo\db\devices.db and restart.",
    "",
    "Windows Server notes",
    "- Prefer an English or normal-permission path, for example C:\NetConsolePortable.",
    "- The app does not use AppData, registry, or system directories.",
    "- Confirm the firewall allows access to 10.0.0.51, 10.0.0.52, and 10.0.0.53.",
    "- If VC runtime or DLL errors appear, install the missing system runtime and retry."
)
$readmeRun | Set-Content -Path (Join-Path $portablePath "README_RUN.txt") -Encoding UTF8

Write-Host "Portable package ready: $portablePath"
