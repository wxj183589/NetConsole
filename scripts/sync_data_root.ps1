[CmdletBinding()]
param(
    [string]$Source = 'D:\NetConsoleData',
    [string]$Target = 'D:\NetConsoleData - dev',
    [switch]$SkipConfirmation
)

$ErrorActionPreference = 'Stop'

function Get-Inventory {
    param([Parameter(Mandatory)][string]$Path)
    $files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -Force)
    [pscustomobject]@{
        Count = $files.Count
        Bytes = [int64](($files | Measure-Object -Property Length -Sum).Sum)
    }
}

function Assert-SafeRoot {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Label)
    $resolved = [System.IO.Path]::GetFullPath($Path)
    if ($resolved -eq [System.IO.Path]::GetPathRoot($resolved)) {
        throw "$Label must not be a drive root: $resolved"
    }
    if ((Get-Item -LiteralPath $resolved -Force -ErrorAction SilentlyContinue) -is [System.IO.DirectoryInfo]) {
        $item = Get-Item -LiteralPath $resolved -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "$Label must not be a junction or symlink: $resolved"
        }
    }
    return $resolved
}

$Source = Assert-SafeRoot -Path $Source -Label 'Source'
$Target = Assert-SafeRoot -Path $Target -Label 'Target'
if ($Source -eq $Target) { throw 'Source and Target must differ.' }
if (-not (Test-Path -LiteralPath $Source -PathType Container)) { throw "Source does not exist: $Source" }
$sourceMarker = Join-Path $Source 'runtime_mode.json'
if (-not (Test-Path -LiteralPath $sourceMarker -PathType Leaf)) {
    throw "Source must contain an explicit runtime_mode.json marker: $sourceMarker"
}
$sourceMode = (Get-Content -LiteralPath $sourceMarker -Raw -Encoding UTF8 | ConvertFrom-Json).mode
if ($sourceMode -ne 'production') {
    throw "Source must be explicitly marked production; found: $sourceMode"
}
$productionRoot = [System.IO.Path]::GetFullPath('D:\NetConsoleData')
if ($Target -eq $productionRoot) {
    throw "Target must never be the production root: $productionRoot"
}
$targetMarker = Join-Path $Target 'runtime_mode.json'
if ((Test-Path -LiteralPath $targetMarker -PathType Leaf) -and
    ((Get-Content -LiteralPath $targetMarker -Raw -Encoding UTF8 | ConvertFrom-Json).mode -eq 'production')) {
    throw "Target is explicitly marked production and cannot be removed: $Target"
}

$sourceInventory = Get-Inventory -Path $Source
Write-Host "SOURCE: $Source"
Write-Host "TARGET: $Target"
Write-Host ("FILES: {0}" -f $sourceInventory.Count)
Write-Host ("BYTES: {0}" -f $sourceInventory.Bytes)

if (-not $SkipConfirmation) {
    $confirmation = Read-Host 'Type SYNC DATA ROOT to continue'
    if ($confirmation -ne 'SYNC DATA ROOT') { throw 'Sync cancelled.' }
}

$start = Get-Date
if (Test-Path -LiteralPath $Target) {
    Remove-Item -LiteralPath $Target -Recurse -Force
}
New-Item -ItemType Directory -Path $Target -Force | Out-Null

& robocopy.exe $Source $Target /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NP | Out-Null
$robocopyExitCode = $LASTEXITCODE
if ($robocopyExitCode -gt 7) { throw "robocopy failed with exit code $robocopyExitCode." }

$manifestPath = Join-Path $Target 'config\storage-manifest.json'
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest.data_root = $Target
    $manifest.installation_id = ([guid]::NewGuid()).ToString('N')
    $manifest.last_opened_at = [DateTime]::UtcNow.ToString('o')
    $manifestJson = ($manifest | ConvertTo-Json -Depth 20) + "`n"
    [System.IO.File]::WriteAllText($manifestPath, $manifestJson, [System.Text.UTF8Encoding]::new($false))
}

$runtimeMode = [ordered]@{
    mode = 'development'
    created_from = $Source
    created_time = [DateTime]::UtcNow.ToString('o')
    readonly_warning = $false
}
$runtimeModePath = Join-Path $Target 'runtime_mode.json'
$runtimeModeJson = ($runtimeMode | ConvertTo-Json) + "`n"
[System.IO.File]::WriteAllText($runtimeModePath, $runtimeModeJson, [System.Text.UTF8Encoding]::new($false))

$targetInventory = Get-Inventory -Path $Target
$elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds, 3)
Write-Host 'SYNC COMPLETE'
Write-Host ("FILES: {0}" -f $targetInventory.Count)
Write-Host ("BYTES: {0}" -f $targetInventory.Bytes)
Write-Host ("TIME_SECONDS: {0}" -f $elapsed)
