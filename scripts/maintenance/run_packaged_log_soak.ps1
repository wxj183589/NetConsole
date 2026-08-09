[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Executable,

    [Parameter(Mandatory = $true)]
    [string]$DataRoot,

    [ValidateRange(1, 1440)]
    [int]$DurationMinutes = 120,

    [ValidateRange(60, 1800)]
    [int]$SampleIntervalSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$testBase = [System.IO.Path]::GetFullPath('D:\NetConsoleTestData').TrimEnd('\')
$resolvedDataRoot = [System.IO.Path]::GetFullPath($DataRoot).TrimEnd('\')
$resolvedExecutable = [System.IO.Path]::GetFullPath($Executable)

if (-not (Test-Path -LiteralPath $resolvedExecutable -PathType Leaf)) {
    throw "Packaged executable was not found: $resolvedExecutable"
}
if (
    $resolvedDataRoot.Equals($testBase, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $resolvedDataRoot.StartsWith("$testBase\", [System.StringComparison]::OrdinalIgnoreCase)
) {
    throw "DataRoot must be an isolated child of $testBase"
}

New-Item -ItemType Directory -Force -Path $resolvedDataRoot | Out-Null
$electronUserData = Join-Path $resolvedDataRoot 'runtime\electron\user-data'
New-Item -ItemType Directory -Force -Path $electronUserData | Out-Null

$resultPath = Join-Path $resolvedDataRoot 'runtime\logs\packaged-log-soak.jsonl'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resultPath) | Out-Null

function Write-JsonLine {
    param([Parameter(Mandatory = $true)] [object]$Value)

    $line = $Value | ConvertTo-Json -Compress -Depth 8
    [System.IO.File]::AppendAllText($resultPath, "$line$([Environment]::NewLine)", $utf8NoBom)
}

function Get-ChildProcessIds {
    param([Parameter(Mandatory = $true)] [int]$RootProcessId)

    $processes = @(Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId)
    $pending = [System.Collections.Generic.Queue[int]]::new()
    $result = [System.Collections.Generic.List[int]]::new()
    $pending.Enqueue($RootProcessId)
    $result.Add($RootProcessId)
    while ($pending.Count -gt 0) {
        $parentId = $pending.Dequeue()
        foreach ($child in $processes | Where-Object { $_.ParentProcessId -eq $parentId }) {
            $childId = [int]$child.ProcessId
            if ($result.Contains($childId)) { continue }
            $result.Add($childId)
            $pending.Enqueue($childId)
        }
    }
    return @($result)
}

function Get-ProcessSnapshot {
    param([int[]]$ProcessIds)

    $items = @()
    foreach ($processId in $ProcessIds) {
        try {
            $process = Get-Process -Id $processId -ErrorAction Stop
            $items += [pscustomobject]@{
                id = $process.Id
                name = $process.ProcessName
                rss_bytes = [int64]$process.WorkingSet64
                cpu_seconds = if ($null -eq $process.CPU) { 0.0 } else { [double]$process.CPU }
            }
        } catch {
            # A short-lived renderer or child can exit between the CIM and process snapshots.
        }
    }
    return @($items)
}

function Get-FileLength {
    param([Parameter(Mandatory = $true)] [string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return 0 }
    return [int64](Get-Item -LiteralPath $Path).Length
}

function Get-DirectoryLength {
    param([Parameter(Mandatory = $true)] [string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return 0 }
    return [int64](Get-ChildItem -LiteralPath $Path -Recurse -Force -File |
        Measure-Object -Property Length -Sum).Sum
}

function Get-ControlEventCount {
    param(
        [Parameter(Mandatory = $true)] [string]$Path,
        [Parameter(Mandatory = $true)] [string]$Event
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return 0 }
    $content = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    return [regex]::Matches($content, "\|\s+$([regex]::Escape($Event))\s+\|").Count
}

function Get-SoakSample {
    param(
        [Parameter(Mandatory = $true)] [System.Diagnostics.Process]$RootProcess,
        [Parameter(Mandatory = $true)] [System.DateTime]$StartedAt
    )

    $processIds = if ($RootProcess.HasExited) { @() } else { Get-ChildProcessIds -RootProcessId $RootProcess.Id }
    $processes = Get-ProcessSnapshot -ProcessIds $processIds
    $electronProcesses = @($processes | Where-Object { $_.name -eq 'NetConsole' })
    $backendProcesses = @($processes | Where-Object { $_.name -eq 'NetConsoleBackend' })
    $logsDir = Join-Path $resolvedDataRoot 'runtime\logs'
    $electronLog = Join-Path $logsDir 'electron.log'
    $appLog = Join-Path $logsDir 'app.log'

    return [pscustomobject]@{
        type = 'sample'
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
        elapsed_seconds = [math]::Round(([DateTime]::UtcNow - $StartedAt).TotalSeconds, 3)
        root_process_alive = -not $RootProcess.HasExited
        process_tree_count = $processes.Count
        electron = [pscustomobject]@{
            process_count = $electronProcesses.Count
            rss_bytes = [int64](($electronProcesses | Measure-Object -Property rss_bytes -Sum).Sum)
            cpu_seconds = [math]::Round([double](($electronProcesses | Measure-Object -Property cpu_seconds -Sum).Sum), 3)
        }
        python = [pscustomobject]@{
            process_count = $backendProcesses.Count
            alive = $backendProcesses.Count -gt 0
            rss_bytes = [int64](($backendProcesses | Measure-Object -Property rss_bytes -Sum).Sum)
            cpu_seconds = [math]::Round([double](($backendProcesses | Measure-Object -Property cpu_seconds -Sum).Sum), 3)
        }
        logs = [pscustomobject]@{
            electron_bytes = Get-FileLength -Path $electronLog
            app_bytes = Get-FileLength -Path $appLog
            total_bytes = Get-DirectoryLength -Path $logsDir
        }
        queue_metrics = [pscustomobject]@{
            externally_available = $false
            backpressure_events = Get-ControlEventCount -Path $electronLog -Event 'LOG_BACKPRESSURE'
            backpressure_recovered_events = Get-ControlEventCount -Path $electronLog -Event 'LOG_BACKPRESSURE_RECOVERED'
        }
    }
}

$environmentNames = @(
    'NETCONSOLE_DATA_ROOT',
    'NETCONSOLE_RUNTIME_MODE',
    'NETCONSOLE_STORAGE_MODE',
    'NETCONSOLE_DEV_TEMP_DATA_ROOT',
    'NETCONSOLE_DEV_TEMP_USER_DATA_ROOT'
)
$originalEnvironment = @{}
foreach ($name in $environmentNames) {
    $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

$startedAt = [DateTime]::UtcNow
$rootProcess = $null
$completedDuration = $false
try {
    $env:NETCONSOLE_DATA_ROOT = $resolvedDataRoot
    $env:NETCONSOLE_RUNTIME_MODE = 'test'
    $env:NETCONSOLE_STORAGE_MODE = 'isolated_test'
    $env:NETCONSOLE_DEV_TEMP_DATA_ROOT = '1'
    $env:NETCONSOLE_DEV_TEMP_USER_DATA_ROOT = $electronUserData
    $rootProcess = Start-Process -FilePath $resolvedExecutable `
        -ArgumentList "--user-data-dir=$electronUserData" `
        -WorkingDirectory (Split-Path -Parent $resolvedExecutable) `
        -PassThru
} finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $originalEnvironment[$name], 'Process')
    }
}

Write-JsonLine ([pscustomobject]@{
    type = 'started'
    timestamp_utc = $startedAt.ToString('o')
    executable = $resolvedExecutable
    data_root = $resolvedDataRoot
    duration_minutes = $DurationMinutes
    sample_interval_seconds = $SampleIntervalSeconds
    root_process_id = $rootProcess.Id
})

try {
    $deadline = $startedAt.AddMinutes($DurationMinutes)
    while ([DateTime]::UtcNow -lt $deadline) {
        $sample = Get-SoakSample -RootProcess $rootProcess -StartedAt $startedAt
        Write-JsonLine $sample
        if (-not $sample.root_process_alive) { break }
        Start-Sleep -Seconds $SampleIntervalSeconds
    }
    $completedDuration = -not $rootProcess.HasExited -and [DateTime]::UtcNow -ge $deadline
} finally {
    $finalSample = Get-SoakSample -RootProcess $rootProcess -StartedAt $startedAt
    Write-JsonLine $finalSample
    $harnessTerminated = -not $rootProcess.HasExited
    $exitCodeBeforeHarnessStop = if ($rootProcess.HasExited) { $rootProcess.ExitCode } else { $null }
    if (-not $rootProcess.HasExited) {
        $tree = Get-ChildProcessIds -RootProcessId $rootProcess.Id
        Stop-Process -Id $rootProcess.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        foreach ($processId in @($tree | Where-Object { $_ -ne $rootProcess.Id })) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    }
    Write-JsonLine ([pscustomobject]@{
        type = 'finished'
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
        completed_duration = $completedDuration
        harness_terminated = $harnessTerminated
        root_process_exit_code_before_harness_stop = $exitCodeBeforeHarnessStop
        result_path = $resultPath
    })
}

if (-not $completedDuration) {
    throw "Packaged soak ended before $DurationMinutes minutes. Evidence: $resultPath"
}

Write-Output "Packaged soak completed. Evidence: $resultPath"
