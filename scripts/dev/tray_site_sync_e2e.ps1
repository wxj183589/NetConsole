[CmdletBinding()]
param(
  [string]$RepoRoot = '',
  [string]$DataRoot = 'D:\NetConsoleData-dev',
  [string]$EvidenceRoot = '',
  [switch]$BuildRenderer
)

$ErrorActionPreference = 'Stop'

function Resolve-AbsolutePath([string]$PathValue, [string]$Description) {
  if ([string]::IsNullOrWhiteSpace($PathValue)) {
    throw "$Description 不能为空"
  }
  try {
    return (Resolve-Path -LiteralPath $PathValue -ErrorAction Stop).Path
  } catch {
    throw "$Description 不存在或不可访问：$PathValue"
  }
}

function ConvertTo-MarkdownCell([string]$Value) {
  if ($null -eq $Value) { return '' }
  return ($Value -replace '[\r\n]+', ' ' -replace '\|', '\|').Trim()
}

function Find-ProjectPython([string]$ProjectRoot) {
  $candidates = [System.Collections.Generic.List[string]]::new()
  if (-not [string]::IsNullOrWhiteSpace($env:NETCONSOLE_PYTHON)) {
    $candidates.Add([IO.Path]::GetFullPath($env:NETCONSOLE_PYTHON))
  }
  $candidates.Add((Join-Path $ProjectRoot '.venv\Scripts\python.exe'))
  try {
    $commonGitDir = (& git -C $ProjectRoot rev-parse --path-format=absolute --git-common-dir 2>$null).Trim()
    if ($LASTEXITCODE -eq 0 -and $commonGitDir) {
      $commonRoot = Split-Path -Parent $commonGitDir
      if (-not $commonRoot.Equals($ProjectRoot, [StringComparison]::OrdinalIgnoreCase)) {
        $candidates.Add((Join-Path $commonRoot '.venv\Scripts\python.exe'))
      }
    }
  } catch {
    # The checkout candidate is still sufficient when git is unavailable.
  }
  foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    try {
      & $candidate --version *> $null
      if ($LASTEXITCODE -eq 0) { return $candidate }
    } catch {
      # Try the next recorded project runtime.
    }
  }
  throw "未找到可执行的项目 Python 运行时；请设置 NETCONSOLE_PYTHON 或准备 .venv\Scripts\python.exe。"
}

function Write-ResultReport(
  [string]$PathValue,
  [string]$RunIdValue,
  [string]$RepoRootValue,
  [string]$DataRootValue,
  [System.Collections.IEnumerable]$ResultsValue,
  [string]$StdoutLogValue,
  [string]$StderrLogValue
) {
  $lines = [System.Collections.Generic.List[string]]::new()
  $lines.Add('# Tray Site Sync E2E 实际记录')
  $lines.Add('')
  $lines.Add("- 验收批次：$RunIdValue")
  $lines.Add('- 测试人：待填写')
  $lines.Add('- 测试日期：待填写')
  $lines.Add("- Repo：$RepoRootValue")
  $lines.Add("- DataRoot：$DataRootValue")
  $lines.Add("- 启动 stdout：$StdoutLogValue")
  $lines.Add("- 启动 stderr：$StderrLogValue")
  $lines.Add('')
  $lines.Add('| 步骤 | 状态 | 实际结果 | 失败截图 |')
  $lines.Add('| --- | --- | --- | --- |')
  foreach ($result in $ResultsValue) {
    $lines.Add("| $($result.Id) | $(ConvertTo-MarkdownCell $result.Status) | $(ConvertTo-MarkdownCell $result.Actual) | $(ConvertTo-MarkdownCell $result.Screenshot) |")
  }
  $lines.Add('')
  $lines.Add('## 诊断日志')
  $lines.Add('')
  $lines.Add('从 Electron 日志或 stdout 搜索 `[TraySync]`，并将三方 `site_id` 填回上表或验收文档。')
  $lines.Add('')
  $lines.Add('## 结论')
  $lines.Add('')
  $lines.Add('- 结论：待填写（只有全部步骤 PASS 才能填写 PASS）')
  Set-Content -LiteralPath $PathValue -Value ($lines -join [Environment]::NewLine) -Encoding utf8
}

$repoRootPath = if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
  Resolve-AbsolutePath (Join-Path $PSScriptRoot '..\..') '脚本推导的仓库根目录'
} else {
  Resolve-AbsolutePath $RepoRoot 'RepoRoot'
}
$dataRootPath = Resolve-AbsolutePath $DataRoot 'DataRoot'
$productionDataRoot = [IO.Path]::GetFullPath('D:\NetConsoleData').TrimEnd('\')
if ($dataRootPath.TrimEnd('\').Equals($productionDataRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw '禁止使用 D:\NetConsoleData 生产数据执行真实验收；请使用 D:\NetConsoleData-dev。'
}

$pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
if (-not $pnpmCommand) { $pnpmCommand = Get-Command pnpm -ErrorAction Stop }
$pnpmPath = $pnpmCommand.Source
if ([string]::IsNullOrWhiteSpace($pnpmPath)) { $pnpmPath = $pnpmCommand.Path }
$pythonPath = Find-ProjectPython $repoRootPath

$runId = Get-Date -Format 'yyyyMMdd-HHmmss'
if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
  $repoParent = Split-Path -Parent $repoRootPath
  $workspaceRoot = if ((Split-Path -Leaf $repoParent) -eq 'worktrees') {
    Split-Path -Parent $repoParent
  } else {
    $repoParent
  }
  $evidenceRootPath = Join-Path $workspaceRoot "diagnostic\tray-site-sync-e2e\$runId"
} else {
  $evidenceRootPath = [IO.Path]::GetFullPath($EvidenceRoot)
}
New-Item -ItemType Directory -Path $evidenceRootPath -Force | Out-Null

$electronRoot = Join-Path $repoRootPath 'apps\desktop_electron'
$rendererRoot = Join-Path $repoRootPath 'apps\desktop_renderer'
$rendererIndex = Join-Path $rendererRoot 'dist\index.html'
$stdoutLog = Join-Path $evidenceRootPath 'launcher.stdout.log'
$stderrLog = Join-Path $evidenceRootPath 'launcher.stderr.log'
$resultReport = Join-Path $evidenceRootPath 'TRAY_SITE_SYNC_E2E_RESULT.md'

if ($BuildRenderer) {
  Write-Host '正在构建 Renderer dist，完成后才会启动人工验收运行时...' -ForegroundColor Cyan
  Push-Location $rendererRoot
  try {
    & $pnpmPath run build
    if ($LASTEXITCODE -ne 0) { throw "Renderer build failed with exit code $LASTEXITCODE" }
  } finally {
    Pop-Location
  }
}
if (-not (Test-Path -LiteralPath $rendererIndex -PathType Leaf)) {
  throw "未找到 Renderer 构建结果：$rendererIndex；请先运行本脚本并添加 -BuildRenderer。"
}

$environmentNames = @(
  'NETCONSOLE_DATA_ROOT',
  'NETCONSOLE_PYTHON',
  'NETCONSOLE_RUNTIME_MODE',
  'NETCONSOLE_DEV_MODE',
  'NETCONSOLE_RENDERER_DEV_URL',
  'NETCONSOLE_ELECTRON_SMOKE_TEST',
  'NETCONSOLE_ELECTRON_TASK_CENTER_SMOKE',
  'NETCONSOLE_ELECTRON_WORKSPACE_TRAY_SMOKE'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
  $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

$launcher = $null
$scriptExitCode = 1
$results = [System.Collections.Generic.List[object]]::new()
$steps = @(
  @{ Id = 1; Action = '启动 Electron；确认主窗口和系统托盘图标出现。'; Expected = 'Electron 主窗口打开，托盘图标出现，无启动致命错误。' },
  @{ Id = 2; Action = '等待并确认 Backend Online。'; Expected = '主界面状态为 Backend Online；离线时 Tray 不显示旧局点。' },
  @{ Id = 3; Action = '记录 Backend 当前局点，并核对 Renderer 顶部和系统设置。'; Expected = '三处使用同一个 site_id；名称仅用于展示。' },
  @{ Id = 4; Action = '右键 Tray，查看当前局点和快速切换 checked 项。'; Expected = 'Tray 显示 Backend 当前局点；checked 由 site_id 决定。' },
  @{ Id = 5; Action = '在系统设置中将局点 A 切换为局点 B。'; Expected = 'Backend 成功后 Renderer 顶部/系统设置变为 B；失败则保持 A。' },
  @{ Id = 6; Action = '重新打开 Tray 菜单检查当前局点和 checked 项。'; Expected = 'Tray 当前局点与 Renderer、Backend 都为 B。' },
  @{ Id = 7; Action = '在 Tray 快速切换中将局点 B 切换为局点 C。'; Expected = '点击传递 site_id；多次快速点击最终按最新成功请求收敛。' },
  @{ Id = 8; Action = '回到 Renderer 页面检查顶部和系统设置。'; Expected = 'Renderer 顶部/系统设置与 Backend、Tray 都为 C。' },
  @{ Id = 9; Action = '点击 Tray → 重启软件；确认旧 Electron 进程退出且新进程启动。'; Expected = '发生真实 app.relaunch/app.exit 重启，不是 Renderer reload。' },
  @{ Id = 10; Action = '重启后等待 Backend Online，重新读取当前局点并核对 Renderer、Tray。'; Expected = '重启后从 Backend 重新读取；四方 site_id 一致。' }
)

try {
  $env:NETCONSOLE_DATA_ROOT = $dataRootPath
  $env:NETCONSOLE_PYTHON = $pythonPath
  $env:NETCONSOLE_RUNTIME_MODE = 'desktop-development'
  $env:NETCONSOLE_DEV_MODE = '1'
  Remove-Item Env:NETCONSOLE_RENDERER_DEV_URL -ErrorAction SilentlyContinue
  Remove-Item Env:NETCONSOLE_ELECTRON_SMOKE_TEST -ErrorAction SilentlyContinue
  Remove-Item Env:NETCONSOLE_ELECTRON_TASK_CENTER_SMOKE -ErrorAction SilentlyContinue
  Remove-Item Env:NETCONSOLE_ELECTRON_WORKSPACE_TRAY_SMOKE -ErrorAction SilentlyContinue

  Write-Host "证据目录：$evidenceRootPath" -ForegroundColor Green
  Write-Host '启动 standalone Electron（不经过 Vite wrapper），便于验证真实重启。' -ForegroundColor Cyan
  $launcher = Start-Process -FilePath $pnpmPath `
    -ArgumentList @('run', 'start') `
    -WorkingDirectory $electronRoot `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru `
    -WindowStyle Normal

  Write-ResultReport $resultReport $runId $repoRootPath $dataRootPath $results $stdoutLog $stderrLog
  Write-Host '请按窗口提示逐项完成人工验收。每一步会记录状态、实际结果和失败截图路径。' -ForegroundColor Yellow
  foreach ($step in $steps) {
    Write-Host "`n步骤 $($step.Id)：$($step.Action)" -ForegroundColor Cyan
    Write-Host "预期：$($step.Expected)"
    do {
      $status = (Read-Host '状态 [PASS/FAIL/BLOCKED/SKIP]').Trim().ToUpperInvariant()
    } while ($status -notin @('PASS', 'FAIL', 'BLOCKED', 'SKIP'))
    $actual = Read-Host '实际结果（可填写 site_id、时间、现象）'
    $screenshot = Read-Host '失败截图位置（无则填写 无）'
    if ([string]::IsNullOrWhiteSpace($screenshot)) { $screenshot = '无' }
    $results.Add([pscustomobject]@{
      Id = $step.Id
      Status = $status
      Actual = $actual
      Screenshot = $screenshot
    })
    Write-ResultReport $resultReport $runId $repoRootPath $dataRootPath $results $stdoutLog $stderrLog
  }
  $scriptExitCode = if (@($results | Where-Object Status -ne 'PASS').Count -eq 0) { 0 } else { 1 }
  Write-Host "`n验收记录已写入：$resultReport" -ForegroundColor Green
  if ($scriptExitCode -ne 0) {
    Write-Host '存在非 PASS 步骤；请根据失败截图和 [TraySync] 日志继续排查。' -ForegroundColor Red
  } else {
    Write-Host '全部步骤标记为 PASS；请在提交前由负责人复核截图和日志。' -ForegroundColor Green
  }
} finally {
  foreach ($name in $environmentNames) {
    $oldValue = $previousEnvironment[$name]
    if ($null -eq $oldValue) {
      Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    } else {
      Set-Item "Env:$name" $oldValue
    }
  }
  if ($launcher -and -not $launcher.HasExited) {
    Write-Host '验收脚本结束；请先从 Tray 退出 NetConsole。脚本不会自动杀进程。' -ForegroundColor Yellow
  }
}

exit $scriptExitCode
