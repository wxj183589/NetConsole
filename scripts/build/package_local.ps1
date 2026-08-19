[CmdletBinding()]
param(
    [ValidateSet("full", "customer", "both", "preflight")]
    [string]$Edition = "both",
    [switch]$NoOpenOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$script:MinimumPasswordLength = 8
$script:MinimumFreeBytes = 10GB
$script:PasswordEnvironmentName = "NETCONSOLE_CUSTOMER_UNLOCK_PASSWORD"
$script:PnpmPathEnvironmentName = "NETCONSOLE_PNPM_PATH"
$script:MutexName = "Global\NetConsoleLocalInstallerBuild"
$script:CorepackPnpmVersion = "11.16.0"
$script:DurableReleaseRoot = "D:\study\release\NetConsole"

function Write-Stage {
    param(
        [Parameter(Mandatory = $true)][int]$Number,
        [Parameter(Mandatory = $true)][string]$Message
    )

    $script:CurrentStage = "[$Number/8] $Message"
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $script:CurrentStage" -ForegroundColor Cyan
}

function Write-StageComplete {
    param(
        [Parameter(Mandatory = $true)][int]$Number,
        [Parameter(Mandatory = $true)][string]$Message
    )

    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Number/8] 完成：$Message" -ForegroundColor DarkCyan
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

function Resolve-PnpmCommand {
    param(
        [Parameter(Mandatory = $true)][string]$NodePath,
        [Parameter(Mandatory = $true)][string]$ProjectRoot
    )

    $command = Get-Command "pnpm.cmd" -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $command) {
        return [PSCustomObject]@{
            Path = $command.Source
            ShimRoot = $null
            Source = "PATH"
        }
    }

    $nodeDirectory = Split-Path -Parent $NodePath
    $corepackPath = Join-Path $nodeDirectory "corepack.cmd"
    if (-not (Test-Path -LiteralPath $corepackPath -PathType Leaf)) {
        $corepack = Get-Command "corepack.cmd" -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -eq $corepack) {
            throw "未找到 pnpm.cmd，且当前 Node.js 未提供 corepack.cmd。请安装包含 Corepack 的 Node.js 24。"
        }
        $corepackPath = $corepack.Source
    }

    $shimContainer = Join-Path $ProjectRoot "dist\_package_tool_shims"
    New-Item -ItemType Directory -Path $shimContainer -Force | Out-Null
    $shimRoot = Join-Path $shimContainer ("package-tool-shim-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $shimRoot | Out-Null
    $shimPath = Join-Path $shimRoot "pnpm.cmd"
    $shimContent = @(
        "@echo off",
        "`"$corepackPath`" pnpm@$script:CorepackPnpmVersion %*",
        "exit /b %ERRORLEVEL%",
        ""
    ) -join "`r`n"
    [System.IO.File]::WriteAllText(
        $shimPath,
        $shimContent,
        [System.Text.UTF8Encoding]::new($true)
    )
    $env:PATH = "$shimRoot$([System.IO.Path]::PathSeparator)$env:PATH"
    return [PSCustomObject]@{
        Path = $shimPath
        ShimRoot = $shimRoot
        Source = "Corepack pnpm@$script:CorepackPnpmVersion（进程内临时代理）"
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
            throw "命令执行失败（退出码 $LASTEXITCODE）：$FilePath"
        }
        return ($output | Out-String).Trim()
    }
    finally {
        Pop-Location
    }
}

function Invoke-PackageWindows {
    param(
        [Parameter(Mandatory = $true)][string]$PowerShellPath,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$PackageScript,
        [Parameter(Mandatory = $true)][string]$BuildEdition,
        [Parameter(Mandatory = $true)][string]$ChildLogPath,
        [switch]$PreflightOnly
    )

    $arguments = @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $PackageScript,
        "-Edition",
        $BuildEdition,
        "-NoOpenOutput"
    )
    if ($PreflightOnly) {
        $arguments += "-PreflightOnly"
    }

    Push-Location -LiteralPath $ProjectRoot
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & $PowerShellPath @arguments 2>&1 |
                Tee-Object -FilePath $ChildLogPath -Append |
                Out-Host
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($exitCode -ne 0) {
            throw "正式构建链失败（退出码 $exitCode）。"
        }
    }
    finally {
        Pop-Location
    }
}

function Convert-SecureStringToPlainText {
    param([Parameter(Mandatory = $true)][System.Security.SecureString]$SecureString)

    $bstr = [IntPtr]::Zero
    try {
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        if ($bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
}

function Read-CustomerPassword {
    param([Parameter(Mandatory = $true)][int]$MinimumLength)

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $first = $null
        $second = $null
        $firstPlain = $null
        $secondPlain = $null
        try {
            $first = Read-Host "请输入客户版维护密码" -AsSecureString
            $second = Read-Host "请再次输入客户版维护密码" -AsSecureString
            $firstPlain = Convert-SecureStringToPlainText $first
            $secondPlain = Convert-SecureStringToPlainText $second
            if (
                -not [string]::IsNullOrWhiteSpace($firstPlain) -and
                $firstPlain.Length -ge $MinimumLength -and
                $firstPlain -ceq $secondPlain
            ) {
                return $firstPlain
            }
        }
        finally {
            if ($null -ne $first) { $first.Dispose() }
            if ($null -ne $second) { $second.Dispose() }
            $firstPlain = $null
            $secondPlain = $null
        }
        if ($attempt -lt 3) {
            Write-Warning "两次输入不一致或不符合密码要求，请重新输入。"
        }
    }
    throw "客户版维护密码确认失败。"
}

function Get-ExpectedEditions {
    param([Parameter(Mandatory = $true)][string]$BuildEdition)

    switch ($BuildEdition) {
        "full" { return @("full") }
        "customer" { return @("customer") }
        default { return @("full", "customer") }
    }
}

function Get-VerifiedArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$ArtifactRoot,
        [Parameter(Mandatory = $true)][string]$Head,
        [Parameter(Mandatory = $true)][string[]]$ExpectedEditions
    )

    $manifests = @(
        Get-ChildItem -LiteralPath $ArtifactRoot -Filter "*.exe.release.json" -File |
            Sort-Object LastWriteTimeUtc -Descending
    )
    $verified = @()
    foreach ($expectedEdition in $ExpectedEditions) {
        $manifestPath = $null
        $manifest = $null
        foreach ($candidate in $manifests) {
            $candidateManifest = Get-Content -LiteralPath $candidate.FullName -Raw -Encoding UTF8 |
                ConvertFrom-Json
            if (
                $candidateManifest.installer_git_commit -eq $Head -and
                $candidateManifest.edition -eq $expectedEdition
            ) {
                $manifestPath = $candidate.FullName
                $manifest = $candidateManifest
                break
            }
        }
        if ($null -eq $manifest) {
            throw "未找到与当前 HEAD 对应的 $expectedEdition 发布清单：$Head"
        }
        if ($manifest.schema -ne "netconsole.installer-release.v1") {
            throw "$expectedEdition 发布清单 schema 不受支持。"
        }
        if ($manifest.feature_profile -ne $expectedEdition) {
            throw "$expectedEdition 发布清单的 feature_profile 不匹配。"
        }
        if ($manifest.packaged_dirty -ne $false) {
            throw "$expectedEdition 发布清单标记 packaged_dirty=true。"
        }
        if ($manifest.published -ne $false) {
            throw "$expectedEdition 本地构建不得标记 published=true。"
        }
        if ($manifest.backend_commit -ne $Head -or $manifest.frontend_commit -ne $Head) {
            throw "$expectedEdition 发布清单的 Backend/Frontend commit 与 Installer commit 不一致。"
        }
        if (
            [string]::IsNullOrWhiteSpace([string]$manifest.version) -or
            $manifest.build_commit -ne $manifest.installer_git_commit -or
            $manifest.build_timestamp -ne $manifest.installer_build_time_utc
        ) {
            throw "$expectedEdition 发布清单的版本或构建事实字段不一致。"
        }
        if ($manifest.edition_payload_verified -ne $true) {
            throw "$expectedEdition 发布清单未通过包内版本策略校验。"
        }
        if ($manifest.real_windows_install_status -ne "PENDING") {
            throw "$expectedEdition 真实 Windows GUI 安装状态必须为 PENDING。"
        }
        if ($manifest.server_installation_status -ne "PENDING") {
            throw "$expectedEdition Server 安装状态必须为 PENDING。"
        }
        if ($manifest.package_smoke -ne "PASS") {
            throw "$expectedEdition 发布清单未记录 package smoke 通过。"
        }
        if ($expectedEdition -eq "customer" -and $manifest.admin_unlock_configured -ne $true) {
            throw "Customer 发布清单缺少维护密码配置标记。"
        }
        if ($expectedEdition -eq "full" -and $manifest.admin_unlock_configured -ne $false) {
            throw "Full 发布清单不应携带维护密码配置标记。"
        }

        $artifactPath = Join-Path $ArtifactRoot ([string]$manifest.artifact_name)
        if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
            throw "$expectedEdition 发布清单指向的安装包不存在：$artifactPath"
        }
        $artifact = Get-Item -LiteralPath $artifactPath
        $actualHash = Get-Sha256Hex -Path $artifactPath
        $expectedHash = ([string]$manifest.artifact_sha256).ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "$expectedEdition 安装包 SHA-256 与发布清单不一致。"
        }
        if ($artifact.Length -ne [int64]$manifest.artifact_size) {
            throw "$expectedEdition 安装包字节数与发布清单不一致。"
        }
        $verified += [PSCustomObject]@{
            Edition = $expectedEdition
            ArtifactPath = $artifactPath
            ManifestPath = $manifestPath
            FileName = $artifact.Name
            Size = [int64]$artifact.Length
            Hash = $actualHash
            Manifest = $manifest
        }
    }
    return $verified
}

function Get-AppVersion {
    param(
        [Parameter(Mandatory = $true)][string]$PythonPath,
        [Parameter(Mandatory = $true)][string]$ProjectRoot
    )

    $version = Invoke-NativeCapture $PythonPath @(
        "-c",
        "from netconsole.core.version import APP_VERSION; print(APP_VERSION)"
    ) $ProjectRoot
    if ($version -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$') {
        throw "无法从 netconsole.core.version 读取有效 APP_VERSION。"
    }
    return $version
}

function Write-ReleaseSummary {
    param(
        [Parameter(Mandatory = $true)][string]$FinalRoot,
        [Parameter(Mandatory = $true)][datetime]$StartedAt,
        [Parameter(Mandatory = $true)][datetime]$CompletedAt,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$Branch,
        [Parameter(Mandatory = $true)][string]$Head,
        [Parameter(Mandatory = $true)][string]$AppVersion,
        [Parameter(Mandatory = $true)][string]$EditionSelection,
        [Parameter(Mandatory = $true)][object[]]$Artifacts
    )

    $summaryArtifacts = @(
        foreach ($artifact in $Artifacts) {
            [ordered]@{
                edition = $artifact.Edition
                filename = $artifact.FileName
                size = [int64]$artifact.Size
                sha256 = $artifact.Hash
                release_manifest = "$($artifact.FileName).release.json"
            }
        }
    )
    $summary = [ordered]@{
        schema = "netconsole.local-package-summary.v1"
        started_at = $StartedAt.ToUniversalTime().ToString("o")
        completed_at = $CompletedAt.ToUniversalTime().ToString("o")
        duration_seconds = [math]::Round(($CompletedAt - $StartedAt).TotalSeconds, 3)
        repository_root = $ProjectRoot
        branch = $Branch
        git_commit = $Head
        git_short = $Head.Substring(0, 8)
        app_version = $AppVersion
        published = $false
        edition_selection = $EditionSelection
        tests_passed = $true
        package_smoke = "PASS"
        artifacts = $summaryArtifacts
        real_windows_install_status = "PENDING"
        server_installation_status = "PENDING"
    }
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $FinalRoot "BUILD_SUMMARY.json") -Encoding UTF8

    $lines = @(
        "# NetConsole 本地打包摘要",
        "",
        "自动构建和包内校验已通过；真实 Windows GUI 安装验收仍为 PENDING。",
        "",
        "- 版本：$AppVersion",
        "- Edition：$EditionSelection",
        "- Git commit：$Head",
        "- 分支：$Branch",
        "- 测试：已通过正式 package_windows 流程",
        "- 真实 Windows GUI 安装：PENDING",
        "",
        "## 制品"
    )
    foreach ($artifact in $Artifacts) {
        $lines += "- $($artifact.Edition)：$($artifact.FileName)，$($artifact.Size) bytes，SHA-256 $($artifact.Hash)"
    }
    $lines += ""
    $lines += "客户维护密码未写入本摘要、日志或制品元数据。"
    $lines | Set-Content -LiteralPath (Join-Path $FinalRoot "BUILD_SUMMARY.md") -Encoding UTF8
}

function Publish-VerifiedArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$AppVersion,
        [Parameter(Mandatory = $true)][string]$Head,
        [Parameter(Mandatory = $true)][string[]]$ExpectedEditions,
        [Parameter(Mandatory = $true)][object[]]$VerifiedArtifacts,
        [Parameter(Mandatory = $true)][datetime]$StartedAt,
        [Parameter(Mandatory = $true)][datetime]$CompletedAt
    )

    $releaseRoot = $script:DurableReleaseRoot
    $normalizedProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
    $normalizedReleaseRoot = [System.IO.Path]::GetFullPath($releaseRoot).TrimEnd("\")
    if ($normalizedReleaseRoot.StartsWith("$normalizedProjectRoot\", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "正式发布根不得位于仓库或 dist 内：$normalizedReleaseRoot"
    }
    New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
    $stagingRoot = Join-Path $releaseRoot (".staging-" + [guid]::NewGuid().ToString("N"))
    $finalRoot = Join-Path (Join-Path $releaseRoot $AppVersion) ("build-{0}-{1}" -f $script:BuildNumber, $Head.Substring(0, 8))
    if (Test-Path -LiteralPath $finalRoot) {
        throw "正式版本目录已存在，拒绝覆盖或混入新候选：$finalRoot"
    }

    New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null
    try {
        $stagedArtifacts = @()
        foreach ($artifact in $VerifiedArtifacts) {
            $destination = Join-Path $stagingRoot $artifact.FileName
            $manifestDestination = "$destination.release.json"
            Copy-Item -LiteralPath $artifact.ArtifactPath -Destination $destination -Force
            Copy-Item -LiteralPath $artifact.ManifestPath -Destination $manifestDestination -Force
            $stagedHash = Get-Sha256Hex -Path $destination
            if ($stagedHash -ne $artifact.Hash) {
                throw "复制后的 $($artifact.Edition) 安装包 SHA-256 校验失败。"
            }
            $stagedArtifacts += [PSCustomObject]@{
                Edition = $artifact.Edition
                FileName = $artifact.FileName
                Size = (Get-Item -LiteralPath $destination).Length
                Hash = $stagedHash
                ManifestPath = $manifestDestination
            }
        }

        $sumLines = @(
            foreach ($artifact in $stagedArtifacts) {
                "$($artifact.Hash)  $($artifact.FileName)"
            }
        )
        $sumLines | Set-Content -LiteralPath (Join-Path $stagingRoot "SHA256SUMS.txt") -Encoding UTF8
        Write-ReleaseSummary -FinalRoot $stagingRoot -StartedAt $StartedAt -CompletedAt $CompletedAt `
            -ProjectRoot $ProjectRoot -Branch $script:Branch -Head $Head -AppVersion $AppVersion `
            -EditionSelection $script:EditionSelection -Artifacts $stagedArtifacts

        Move-Item -LiteralPath $stagingRoot -Destination $finalRoot
        return [PSCustomObject]@{
            FinalRoot = $finalRoot
            Artifacts = $stagedArtifacts
        }
    }
    catch {
        if (Test-Path -LiteralPath $stagingRoot) {
            Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

$mutex = $null
$mutexAcquired = $false
$transcriptStarted = $false
$originalPasswordPresent = Test-Path "Env:$script:PasswordEnvironmentName"
$originalPassword = if ($originalPasswordPresent) { [Environment]::GetEnvironmentVariable($script:PasswordEnvironmentName, "Process") } else { $null }
$startedAt = Get-Date
$logPath = $null
$childLogPath = $null
$stagingRoot = $null
$pnpmShimRoot = $null
$originalProcessPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
$buildEnvironmentNames = @($script:PnpmPathEnvironmentName, "PYTHONUTF8", "PYTHONIOENCODING")
$originalBuildEnvironment = @{}
foreach ($environmentName in $buildEnvironmentNames) {
    $originalBuildEnvironment[$environmentName] = [PSCustomObject]@{
        Present = Test-Path -LiteralPath "Env:$environmentName"
        Value = [Environment]::GetEnvironmentVariable($environmentName, "Process")
    }
}
$script:CurrentStage = "初始化"

try {
    $scriptDirectory = Split-Path -Parent $PSCommandPath
    $projectRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDirectory "..\..")).Path
    $logRoot = Join-Path $projectRoot "dist\package-logs"
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $logPath = Join-Path $logRoot ("package-" + $startedAt.ToString("yyyyMMdd-HHmmss") + ".log")
    $childLogPath = Join-Path $logRoot ("package-" + $startedAt.ToString("yyyyMMdd-HHmmss") + ".child.log")
    Start-Transcript -LiteralPath $logPath -Force | Out-Null
    $transcriptStarted = $true

    $mutex = New-Object System.Threading.Mutex($false, $script:MutexName)
    try {
        $mutexAcquired = $mutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        $mutexAcquired = $true
    }
    if (-not $mutexAcquired) {
        throw "已有 NetConsole 打包任务正在运行。"
    }

    $script:EditionSelection = $Edition
    Write-Stage 1 "检查构建环境"
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw "正式安装包只能在 Windows 上构建。"
    }
    $gitPath = Resolve-NativeCommand "git.exe"
    $nodePath = Resolve-NativeCommand "node.exe"
    $pnpmResolution = Resolve-PnpmCommand -NodePath $nodePath -ProjectRoot $projectRoot
    $pnpmPath = $pnpmResolution.Path
    $pnpmShimRoot = $pnpmResolution.ShimRoot
    [Environment]::SetEnvironmentVariable($script:PnpmPathEnvironmentName, $pnpmPath, "Process")
    [Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "Process")
    [Environment]::SetEnvironmentVariable("PYTHONIOENCODING", "utf-8", "Process")
    $powerShellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $powerShellPath)) {
        throw "未找到 Windows PowerShell 5.1：$powerShellPath"
    }
    $desktopRoot = Join-Path $projectRoot "apps\desktop_electron"
    $rendererRoot = Join-Path $projectRoot "apps\desktop_renderer"
    $pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $packageScript = Join-Path $projectRoot "scripts\build\package_windows.ps1"
    foreach ($requiredPath in @(
        $pythonPath,
        $packageScript,
        (Join-Path $desktopRoot "package.json"),
        (Join-Path $desktopRoot "pnpm-lock.yaml"),
        (Join-Path $rendererRoot "package.json"),
        (Join-Path $rendererRoot "pnpm-lock.yaml")
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "缺少正式打包所需文件：$requiredPath"
        }
    }
    $driveRoot = [System.IO.Path]::GetPathRoot($projectRoot)
    $driveInfo = New-Object System.IO.DriveInfo($driveRoot)
    if ($driveInfo.AvailableFreeSpace -lt $script:MinimumFreeBytes) {
        throw "构建磁盘剩余空间不足。"
    }

    Write-Stage 2 "检查 Git 工作区和 upstream"
    $actualRoot = Invoke-NativeCapture $gitPath @("rev-parse", "--show-toplevel") $projectRoot
    $normalizedActualRoot = (Resolve-Path -LiteralPath $actualRoot).Path
    if ($normalizedActualRoot -ne $projectRoot) {
        throw "脚本所在仓库与 Git 根目录不一致：$normalizedActualRoot"
    }
    $dirty = Invoke-NativeCapture $gitPath @("status", "--porcelain", "--untracked-files=all") $projectRoot
    if ($dirty) {
        throw "工作区存在未提交修改，未自动 add/commit/reset/checkout/clean/stash/push。`n$dirty"
    }
    $head = Invoke-NativeCapture $gitPath @("rev-parse", "HEAD") $projectRoot
    try {
        $upstream = Invoke-NativeCapture $gitPath @("rev-parse", "@{upstream}") $projectRoot
    }
    catch {
        throw "当前分支未配置 upstream。"
    }
    if ($head -ne $upstream) {
        throw "当前 HEAD 尚未与 upstream 对齐。"
    }
    $script:Branch = Invoke-NativeCapture $gitPath @("rev-parse", "--abbrev-ref", "HEAD") $projectRoot
    Write-Host "项目根目录：$projectRoot"
    Write-Host "当前分支：$script:Branch"
    Write-Host "Git commit：$head"
    Write-Host "版本选择：$Edition"
    Write-Host "Python：$(Invoke-NativeCapture $pythonPath @('--version') $projectRoot)"
    Write-Host "Node.js：$(Invoke-NativeCapture $nodePath @('--version') $projectRoot)"
    Write-Host "pnpm：$(Invoke-NativeCapture $pnpmPath @('--version') $projectRoot)"
    Write-Host "pnpm 来源：$($pnpmResolution.Source)"
    Invoke-NativeCapture $pythonPath @("-m", "pip", "check") $projectRoot | Out-Null
    Write-Host "pip check：通过"
    Write-StageComplete 1 "构建环境"
    Write-StageComplete 2 "Git 工作区和 upstream"

    if ($Edition -eq "preflight") {
        Write-Stage 3 "预检模式"
        Invoke-PackageWindows -PowerShellPath $powerShellPath -ProjectRoot $projectRoot `
            -PackageScript $packageScript -BuildEdition "both" -ChildLogPath $childLogPath -PreflightOnly
        Write-StageComplete 3 "预检模式"
        Write-Host "预检通过；未安装依赖、未运行测试、未生成安装包。" -ForegroundColor Green
        exit 0
    }

    $needsCustomerPassword = $Edition -eq "customer" -or $Edition -eq "both"
    Write-Stage 3 "准备客户版维护密码"
    if ($needsCustomerPassword) {
        $currentPassword = [Environment]::GetEnvironmentVariable($script:PasswordEnvironmentName, "Process")
        if ([string]::IsNullOrWhiteSpace($currentPassword) -or $currentPassword.Length -lt $script:MinimumPasswordLength) {
            $currentPassword = Read-CustomerPassword -MinimumLength $script:MinimumPasswordLength
        }
        [Environment]::SetEnvironmentVariable($script:PasswordEnvironmentName, $currentPassword, "Process")
        $currentPassword = $null
    }
    else {
        Write-Host "Full-only 构建不需要客户版维护密码。"
    }
    Write-StageComplete 3 "客户版维护密码"

    Write-Stage 4 "安装锁定依赖"
    Write-Stage 5 "运行 Web 与 Electron 测试"
    Write-Stage 6 "构建 $Edition 安装包"
    Write-Stage 7 "验证安装包和发布清单"
    Invoke-PackageWindows -PowerShellPath $powerShellPath -ProjectRoot $projectRoot `
        -PackageScript $packageScript -BuildEdition $Edition -ChildLogPath $childLogPath
    Write-StageComplete 4 "锁定依赖"
    Write-StageComplete 5 "Web 与 Electron 测试"
    Write-StageComplete 6 "安装包构建"
    Write-StageComplete 7 "安装包和发布清单验证"

    $finalDirty = Invoke-NativeCapture $gitPath @("status", "--porcelain", "--untracked-files=all") $projectRoot
    $finalHead = Invoke-NativeCapture $gitPath @("rev-parse", "HEAD") $projectRoot
    $finalUpstream = Invoke-NativeCapture $gitPath @("rev-parse", "@{upstream}") $projectRoot
    if ($finalDirty -or $finalHead -ne $head -or $finalUpstream -ne $head) {
        throw "构建结束时源码状态已变化，拒绝发布。frozen=$head，HEAD=$finalHead，upstream=$finalUpstream"
    }
    $expectedEditions = Get-ExpectedEditions -BuildEdition $Edition
    $artifactRoot = Join-Path $projectRoot "dist\electron"
    $verified = Get-VerifiedArtifacts -ArtifactRoot $artifactRoot -Head $head -ExpectedEditions $expectedEditions
    $publishDirty = Invoke-NativeCapture $gitPath @("status", "--porcelain", "--untracked-files=all") $projectRoot
    if ($publishDirty -or (Invoke-NativeCapture $gitPath @("rev-parse", "HEAD") $projectRoot) -ne $head -or (Invoke-NativeCapture $gitPath @("rev-parse", "@{upstream}") $projectRoot) -ne $head) {
        throw "发布前源码状态已变化，拒绝写入正式发布目录。"
    }
    $appVersion = Get-AppVersion -PythonPath $pythonPath -ProjectRoot $projectRoot
    $rawBuildNumber = if ([string]::IsNullOrWhiteSpace($env:NETCONSOLE_BUILD_NUMBER)) { "0" } else { $env:NETCONSOLE_BUILD_NUMBER }
    $script:BuildNumber = 0
    if (-not [int]::TryParse($rawBuildNumber, [ref]$script:BuildNumber) -or $script:BuildNumber -lt 0 -or $script:BuildNumber -gt 65535) {
        throw "NETCONSOLE_BUILD_NUMBER 必须位于 0..65535。"
    }
    $completedAt = Get-Date
    $published = Publish-VerifiedArtifacts -ProjectRoot $projectRoot -AppVersion $appVersion -Head $head `
        -ExpectedEditions $expectedEditions -VerifiedArtifacts $verified -StartedAt $startedAt -CompletedAt $completedAt

    Write-Stage 8 "整理发布制品"
    Write-Host "自动构建和包内校验已通过；真实 Windows GUI 安装验收仍为 PENDING。" -ForegroundColor Green
    Write-Host "发布目录：$($published.FinalRoot)"
    foreach ($artifact in $published.Artifacts) {
        Write-Host "[$($artifact.Edition)] $($artifact.FileName)"
        Write-Host "[$($artifact.Edition)] $($artifact.Size) bytes"
        Write-Host "[$($artifact.Edition)] SHA-256：$($artifact.Hash)"
    }
    Write-StageComplete 8 "发布制品"
    if (-not $NoOpenOutput) {
        try {
            Start-Process -FilePath "explorer.exe" -ArgumentList @($published.FinalRoot) -ErrorAction Stop | Out-Null
        }
        catch {
            Write-Warning "Explorer 打开失败；请手动打开：$($published.FinalRoot)"
        }
    }
    exit 0
}
catch {
    Write-Host ""
    $failedAt = Get-Date
    $duration = [math]::Round(($failedAt - $startedAt).TotalSeconds, 3)
    Write-Error "自动打包失败（阶段：$script:CurrentStage，总耗时：${duration}s）：$($_.Exception.Message)"
    if ($null -ne $logPath) {
        Write-Host "失败日志：$logPath" -ForegroundColor Yellow
    }
    exit 1
}
finally {
    foreach ($environmentName in $buildEnvironmentNames) {
        $originalEnvironment = $originalBuildEnvironment[$environmentName]
        if ($originalEnvironment.Present) {
            [Environment]::SetEnvironmentVariable(
                $environmentName,
                $originalEnvironment.Value,
                "Process"
            )
        }
        else {
            Remove-Item -LiteralPath "Env:$environmentName" -ErrorAction SilentlyContinue
        }
    }
    if ($null -ne $pnpmShimRoot) {
        [Environment]::SetEnvironmentVariable("PATH", $originalProcessPath, "Process")
        $resolvedShimContainer = [System.IO.Path]::GetFullPath(
            (Join-Path $projectRoot "dist\_package_tool_shims")
        )
        $resolvedShimRoot = [System.IO.Path]::GetFullPath($pnpmShimRoot)
        if (
            [System.IO.Path]::GetDirectoryName($resolvedShimRoot) -eq $resolvedShimContainer -and
            [System.IO.Path]::GetFileName($resolvedShimRoot).StartsWith("package-tool-shim-", [StringComparison]::Ordinal)
        ) {
            Remove-Item -LiteralPath $resolvedShimRoot -Recurse -Force -ErrorAction SilentlyContinue
            if (
                (Test-Path -LiteralPath $resolvedShimContainer -PathType Container) -and
                @(Get-ChildItem -LiteralPath $resolvedShimContainer -Force).Count -eq 0
            ) {
                Remove-Item -LiteralPath $resolvedShimContainer -Force -ErrorAction SilentlyContinue
            }
        }
    }
    if ($originalPasswordPresent) {
        [Environment]::SetEnvironmentVariable($script:PasswordEnvironmentName, $originalPassword, "Process")
    }
    else {
        $environmentPath = "Env:$script:PasswordEnvironmentName"
        Remove-Item -LiteralPath $environmentPath -ErrorAction SilentlyContinue
    }
    if ($mutexAcquired -and $null -ne $mutex) {
        try { $mutex.ReleaseMutex() } catch { }
    }
    if ($null -ne $mutex) {
        $mutex.Dispose()
    }
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
    if (
        $null -ne $childLogPath -and
        $null -ne $logPath -and
        (Test-Path -LiteralPath $childLogPath -PathType Leaf)
    ) {
        Get-Content -LiteralPath $childLogPath |
            Add-Content -LiteralPath $logPath -Encoding UTF8
        Remove-Item -LiteralPath $childLogPath -Force -ErrorAction SilentlyContinue
    }
}
