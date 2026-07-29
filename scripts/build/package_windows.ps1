[CmdletBinding()]
param(
    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-NativeCommand {
    param([Parameter(Mandatory = $true)][string]$Name)

    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $command) {
        throw "未找到命令：$Name"
    }
    return $command.Source
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "命令执行失败（退出码 $LASTEXITCODE）：$FilePath $($ArgumentList -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    Push-Location -LiteralPath $WorkingDirectory
    try {
        $output = & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "命令执行失败（退出码 $LASTEXITCODE）：$FilePath $($ArgumentList -join ' ')"
        }
        return ($output | Out-String).Trim()
    }
    finally {
        Pop-Location
    }
}

try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw "正式安装包只能在 Windows 上构建。"
    }

    $scriptDirectory = Split-Path -Parent $PSCommandPath
    $projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDirectory "..\..")).Path
    $desktopRoot = Join-Path $projectRoot "apps\desktop_electron"
    $webRoot = Join-Path $projectRoot "apps\web"
    $pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $artifactRoot = Join-Path $projectRoot "dist\electron"

    Write-Step "检查构建环境"
    $gitPath = Resolve-NativeCommand "git.exe"
    $nodePath = Resolve-NativeCommand "node.exe"
    $pnpmPath = Resolve-NativeCommand "pnpm.cmd"

    foreach ($requiredPath in @(
        $pythonPath,
        (Join-Path $desktopRoot "package.json"),
        (Join-Path $desktopRoot "pnpm-lock.yaml"),
        (Join-Path $webRoot "package.json"),
        (Join-Path $webRoot "pnpm-lock.yaml")
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "缺少正式打包所需文件：$requiredPath"
        }
    }

    $actualRoot = Invoke-NativeCapture $gitPath @("rev-parse", "--show-toplevel") $projectRoot
    $normalizedActualRoot = (Resolve-Path -LiteralPath $actualRoot).Path
    if ($normalizedActualRoot -ne $projectRoot) {
        throw "脚本所在仓库与 Git 根目录不一致：$normalizedActualRoot"
    }

    $dirty = Invoke-NativeCapture $gitPath @("status", "--porcelain", "--untracked-files=all") $projectRoot
    if ($dirty) {
        throw "工作区存在未提交修改，正式打包已停止。请先提交并推送本次修改。`n$dirty"
    }

    $head = Invoke-NativeCapture $gitPath @("rev-parse", "HEAD") $projectRoot
    $upstream = Invoke-NativeCapture $gitPath @("rev-parse", "@{upstream}") $projectRoot
    if ($head -ne $upstream) {
        throw "当前 HEAD 尚未与 upstream 对齐。HEAD=$head，upstream=$upstream"
    }

    $pythonVersion = Invoke-NativeCapture $pythonPath @("--version") $projectRoot
    $nodeVersion = Invoke-NativeCapture $nodePath @("--version") $projectRoot
    $pnpmVersion = Invoke-NativeCapture $pnpmPath @("--version") $projectRoot
    Write-Host "Git HEAD : $head"
    Write-Host "Python   : $pythonVersion"
    Write-Host "Node.js  : $nodeVersion"
    Write-Host "pnpm     : $pnpmVersion"

    Invoke-Native $pythonPath @("-m", "pip", "check") $projectRoot

    if ($PreflightOnly) {
        Write-Host ""
        Write-Host "预检通过；未安装依赖、未运行测试、未生成安装包。" -ForegroundColor Green
        exit 0
    }

    Write-Step "安装 Web 锁定依赖"
    Invoke-Native $pnpmPath @("install", "--frozen-lockfile") $webRoot

    Write-Step "安装 Electron 锁定依赖"
    Invoke-Native $pnpmPath @("install", "--frozen-lockfile") $desktopRoot

    Write-Step "运行 Web 测试"
    Invoke-Native $pnpmPath @("test") $webRoot

    Write-Step "运行 Electron 测试"
    Invoke-Native $pnpmPath @("test") $desktopRoot

    Write-Step "构建并验证正式 Windows 安装包"
    Invoke-Native $pnpmPath @("package") $desktopRoot

    Write-Step "复核发布清单与安装包"
    $manifests = @(
        Get-ChildItem -LiteralPath $artifactRoot -Filter "*.exe.release.json" -File |
            Sort-Object LastWriteTimeUtc -Descending
    )
    $releaseManifestPath = $null
    $releaseManifest = $null
    foreach ($candidate in $manifests) {
        $candidateManifest = Get-Content -LiteralPath $candidate.FullName -Raw -Encoding UTF8 |
            ConvertFrom-Json
        if ($candidateManifest.installer_git_commit -eq $head) {
            $releaseManifestPath = $candidate.FullName
            $releaseManifest = $candidateManifest
            break
        }
    }
    if ($null -eq $releaseManifest) {
        throw "未找到与当前 HEAD 对应的安装包发布清单：$head"
    }

    if ($releaseManifest.schema -ne "netconsole.installer-release.v1") {
        throw "发布清单 schema 不受支持：$($releaseManifest.schema)"
    }
    if ($releaseManifest.packaged_dirty -ne $false) {
        throw "发布清单标记 packaged_dirty=true，拒绝交付。"
    }
    if ($releaseManifest.real_windows_install_status -ne "PENDING") {
        throw "自动构建的真实安装状态必须为 PENDING。"
    }

    $artifactPath = Join-Path $artifactRoot $releaseManifest.artifact_name
    if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
        throw "发布清单指向的安装包不存在：$artifactPath"
    }

    $artifact = Get-Item -LiteralPath $artifactPath
    $actualHash = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedHash = ([string]$releaseManifest.artifact_sha256).ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "安装包 SHA-256 与发布清单不一致。expected=$expectedHash，actual=$actualHash"
    }
    if ($artifact.Length -ne [int64]$releaseManifest.artifact_size) {
        throw "安装包字节数与发布清单不一致。expected=$($releaseManifest.artifact_size)，actual=$($artifact.Length)"
    }

    Write-Host ""
    Write-Host "自动打包完成。" -ForegroundColor Green
    Write-Host "安装包 : $artifactPath"
    Write-Host "发布清单: $releaseManifestPath"
    Write-Host "文件大小: $($artifact.Length) bytes"
    Write-Host "SHA-256 : $actualHash"
    Write-Host "真实 GUI 安装验收状态仍为 PENDING，发布前需按文档完成人工验收。"
    exit 0
}
catch {
    Write-Host ""
    Write-Error "自动打包失败：$($_.Exception.Message)"
    exit 1
}
