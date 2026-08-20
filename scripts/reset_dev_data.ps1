[CmdletBinding()]
param(
    [string]$Source = 'D:\NetConsoleData',
    [string]$Target = 'D:\NetConsoleData - dev'
)

$ErrorActionPreference = 'Stop'
$productionRoot = [System.IO.Path]::GetFullPath('D:\NetConsoleData')
$targetRoot = [System.IO.Path]::GetFullPath($Target)
if ($targetRoot -eq $productionRoot) { throw "Target must never be the production root: $productionRoot" }
if (-not (Test-Path -LiteralPath $Source -PathType Container)) { throw "Source does not exist: $Source" }
$first = Read-Host 'Type RESET DEV DATA to continue'
if ($first -ne 'RESET DEV DATA') { throw 'Reset cancelled.' }
$second = Read-Host 'Type RESET DEV DATA again to confirm'
if ($second -ne 'RESET DEV DATA') { throw 'Reset cancelled.' }

$syncScript = Join-Path $PSScriptRoot 'sync_data_root.ps1'
& $syncScript -Source $Source -Target $Target -SkipConfirmation
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
