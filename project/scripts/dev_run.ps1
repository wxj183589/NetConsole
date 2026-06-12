$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

if (Test-Path ".\.venv\Scripts\python.exe") {
    .\.venv\Scripts\python.exe main.py
} else {
    python main.py
}
