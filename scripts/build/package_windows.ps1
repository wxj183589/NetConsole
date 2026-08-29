[CmdletBinding()]
param(
    [ValidateSet("full", "customer", "both")]
    [string]$Edition = "both",
    [switch]$NoOpenOutput,
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

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            return ([System.BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
        }
        finally {
            $sha256.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
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
    $rendererRoot = Join-Path $projectRoot "apps\desktop_renderer"
    $pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $artifactRoot = Join-Path $projectRoot "dist\electron"
    $expectedEditions = switch ($Edition) {
        "full" { @("full"); break }
        "customer" { @("customer"); break }
        default { @("full", "customer") }
    }

    Write-Step "检查构建环境"
    $gitPath = Resolve-NativeCommand "git.exe"
    $nodePath = Resolve-NativeCommand "node.exe"
    $pnpmPath = Resolve-NativeCommand "pnpm.cmd"

    foreach ($requiredPath in @(
        $pythonPath,
        (Join-Path $desktopRoot "package.json"),
        (Join-Path $desktopRoot "pnpm-lock.yaml"),
        (Join-Path $rendererRoot "package.json"),
        (Join-Path $rendererRoot "pnpm-lock.yaml")
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

    if ($Edition -ne "full") {
        $passwordSource = Invoke-NativeCapture $pythonPath @(
            "-c",
            "from netconsole.core.feature_flags import resolve_customer_unlock_password; print(resolve_customer_unlock_password().source)"
        ) $projectRoot
        Write-Host "CUSTOMER_PASSWORD_SOURCE=$passwordSource"
        Write-Host "CUSTOMER_BUILD_PREFLIGHT=PASS"
    }

    if ($PreflightOnly) {
        Write-Host ""
        Write-Host "预检通过；未安装依赖、未运行测试、未生成安装包。" -ForegroundColor Green
        exit 0
    }

    Write-Step "安装 Web 锁定依赖"
    Invoke-Native $pnpmPath @("install", "--frozen-lockfile") $rendererRoot

    Write-Step "安装 Electron 锁定依赖"
    Invoke-Native $pnpmPath @("install", "--frozen-lockfile") $desktopRoot
    $electronInstallScript = Join-Path $desktopRoot "node_modules\electron\install.js"
    $electronExecutable = Join-Path $desktopRoot "node_modules\electron\dist\electron.exe"
    if (-not (Test-Path -LiteralPath $electronExecutable -PathType Leaf)) {
        if (-not (Test-Path -LiteralPath $electronInstallScript -PathType Leaf)) {
            throw "Electron 锁定依赖缺少安装脚本：$electronInstallScript"
        }
        Write-Host "Electron 分发目录缺失，正在按锁定版本恢复。"
        Invoke-Native $nodePath @($electronInstallScript) $desktopRoot
    }
    if (-not (Test-Path -LiteralPath $electronExecutable -PathType Leaf)) {
        throw "Electron 分发目录恢复失败：$electronExecutable"
    }

    Write-Step "运行 Web 测试"
    $hadVitestParallelGate = Test-Path Env:NETCONSOLE_VITEST_PARALLEL_GATE
    $previousVitestParallelGate = $env:NETCONSOLE_VITEST_PARALLEL_GATE
    try {
        $env:NETCONSOLE_VITEST_PARALLEL_GATE = "1"
        Invoke-Native $pnpmPath @("test") $rendererRoot
    }
    finally {
        if ($hadVitestParallelGate) {
            $env:NETCONSOLE_VITEST_PARALLEL_GATE = $previousVitestParallelGate
        }
        else {
            Remove-Item Env:NETCONSOLE_VITEST_PARALLEL_GATE -ErrorAction SilentlyContinue
        }
    }

    Write-Step "运行 Electron 测试"
    Invoke-Native $pnpmPath @("test") $desktopRoot

    $packageScript = switch ($Edition) {
        "full" { "package:full" }
        "customer" { "package:customer" }
        default { "package:all" }
    }
    Write-Step "构建并验证 $Edition Windows 安装包"
    Invoke-Native $pnpmPath @("run", $packageScript) $desktopRoot

    $finalDirty = Invoke-NativeCapture $gitPath @("status", "--porcelain", "--untracked-files=all") $projectRoot
    $finalHead = Invoke-NativeCapture $gitPath @("rev-parse", "HEAD") $projectRoot
    $finalUpstream = Invoke-NativeCapture $gitPath @("rev-parse", "@{upstream}") $projectRoot
    if ($finalDirty -or $finalHead -ne $head -or $finalUpstream -ne $head) {
        throw "构建结束时源码状态已变化，拒绝交付。frozen=$head，HEAD=$finalHead，upstream=$finalUpstream"
    }

    Write-Step "复核双版本发布清单与安装包"
    $manifests = @(
        Get-ChildItem -LiteralPath $artifactRoot -Filter "*.exe.release.json" -File |
            Sort-Object LastWriteTimeUtc -Descending
    )
    $verified = @()
    foreach ($edition in $expectedEditions) {
        $releaseManifestPath = $null
        $releaseManifest = $null
        foreach ($candidate in $manifests) {
            $candidateManifest = Get-Content -LiteralPath $candidate.FullName -Raw -Encoding UTF8 |
                ConvertFrom-Json
            if (
                $candidateManifest.installer_git_commit -eq $head -and
                $candidateManifest.edition -eq $edition
            ) {
                $releaseManifestPath = $candidate.FullName
                $releaseManifest = $candidateManifest
                break
            }
        }
        if ($null -eq $releaseManifest) {
            throw "未找到与当前 HEAD 对应的 $edition 安装包发布清单：$head"
        }
        if ($releaseManifest.schema -ne "netconsole.installer-release.v1") {
            throw "$edition 发布清单 schema 不受支持：$($releaseManifest.schema)"
        }
        if ($releaseManifest.packaged_dirty -ne $false) {
            throw "$edition 发布清单标记 packaged_dirty=true，拒绝交付。"
        }
        if ($releaseManifest.backend_commit -ne $head -or $releaseManifest.frontend_commit -ne $head) {
            throw "$edition 发布清单的 Backend/Frontend commit 与 Installer commit 不一致。"
        }
        if (
            [string]::IsNullOrWhiteSpace([string]$releaseManifest.version) -or
            $releaseManifest.build_commit -ne $releaseManifest.installer_git_commit -or
            $releaseManifest.build_timestamp -ne $releaseManifest.installer_build_time_utc
        ) {
            throw "$edition 发布清单的版本或构建事实字段不一致。"
        }
        if ($releaseManifest.real_windows_install_status -ne "PENDING") {
            throw "$edition 自动构建的真实安装状态必须为 PENDING。"
        }
        if ($releaseManifest.server_installation_status -ne "PENDING") {
            throw "$edition Server 安装状态必须为 PENDING。"
        }
        if ($releaseManifest.package_smoke -ne "PASS") {
            throw "$edition 发布清单未记录 package smoke 通过。"
        }
        if ($releaseManifest.feature_profile -ne $edition) {
            throw "$edition 发布清单的 feature_profile 不匹配。"
        }
        if ($releaseManifest.edition_payload_verified -ne $true) {
            throw "$edition 发布清单未通过包内版本策略校验。"
        }
        if ($edition -eq "customer" -and $releaseManifest.admin_unlock_configured -ne $true) {
            throw "客户版未配置维护密码哈希。"
        }
        if ($edition -eq "full" -and $releaseManifest.admin_unlock_configured -ne $false) {
            throw "完整版不应携带客户维护密码哈希。"
        }

        $artifactPath = Join-Path $artifactRoot $releaseManifest.artifact_name
        if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
            throw "$edition 发布清单指向的安装包不存在：$artifactPath"
        }
        $artifact = Get-Item -LiteralPath $artifactPath
        $actualHash = Get-Sha256Hex -Path $artifactPath
        $expectedHash = ([string]$releaseManifest.artifact_sha256).ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "$edition 安装包 SHA-256 与发布清单不一致。expected=$expectedHash，actual=$actualHash"
        }
        if ($artifact.Length -ne [int64]$releaseManifest.artifact_size) {
            throw "$edition 安装包字节数与发布清单不一致。expected=$($releaseManifest.artifact_size)，actual=$($artifact.Length)"
        }
        $verified += [PSCustomObject]@{
            Edition = $edition
            ArtifactPath = $artifactPath
            ManifestPath = $releaseManifestPath
            Size = $artifact.Length
            Hash = $actualHash
        }
    }

    Write-Host ""
    Write-Host "双版本自动打包完成。" -ForegroundColor Green
    foreach ($item in $verified) {
        Write-Host "[$($item.Edition)] 安装包 : $($item.ArtifactPath)"
        Write-Host "[$($item.Edition)] 发布清单: $($item.ManifestPath)"
        Write-Host "[$($item.Edition)] 文件大小: $($item.Size) bytes"
        Write-Host "[$($item.Edition)] SHA-256 : $($item.Hash)"
    }
    Write-Host "真实 GUI 安装验收状态仍为 PENDING，发布前需按文档完成人工验收。"
    if (-not $NoOpenOutput) {
        try {
            Start-Process -FilePath "explorer.exe" -ArgumentList @($artifactRoot) -ErrorAction Stop | Out-Null
        }
        catch {
            Write-Warning "无法自动打开制品目录：$artifactRoot；请手动打开。"
        }
    }
    exit 0
}
catch {
    Write-Host ""
    Write-Error "自动打包失败：$($_.Exception.Message)"
    exit 1
}
