[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ToolRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($null -eq $Actual -or $null -eq $Expected) {
        if (-not ($null -eq $Actual -and $null -eq $Expected)) {
            throw "$Label mismatch: one value is null."
        }
        return
    }
    if ($Actual.GetType() -ne $Expected.GetType()) {
        throw "$Label type mismatch: expected '$($Expected.GetType().FullName)', got '$($Actual.GetType().FullName)'."
    }
    if (($Actual -is [string] -and $Actual -cne $Expected) -or ($Actual -isnot [string] -and $Actual -ne $Expected)) {
        throw "$Label mismatch: expected '$Expected', got '$Actual'."
    }
}

function Assert-FileHash {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$ExpectedHash
    )

    $path = Join-Path $script:ResolvedToolRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required runtime tool file is missing: $path"
    }

    $actualHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $ExpectedHash.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $path. Expected $ExpectedHash, got $actualHash."
    }
}

function Read-Provenance {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $path = Join-Path $script:ResolvedToolRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Runtime tool provenance is missing: $path"
    }

    try {
        return [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    }
    catch {
        throw "Runtime tool provenance is invalid JSON: $path ($($_.Exception.Message))"
    }
}

function Assert-ExactNamedEntries {
    param(
        [AllowEmptyCollection()][Parameter(Mandatory = $true)]$Items,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $entries = @($Items)
    $actualNames = @($entries | ForEach-Object { [string]$_.name })
    $duplicateNames = @(
        $actualNames | Group-Object | Where-Object { $_.Count -ne 1 } | ForEach-Object { $_.Name }
    )
    if ($duplicateNames.Count -gt 0) {
        throw "$Label contains duplicate entries: $($duplicateNames -join ', ')"
    }

    $expectedNames = @($Expected.Keys | ForEach-Object { [string]$_ })
    $unexpectedNames = @($actualNames | Where-Object { $expectedNames -cnotcontains $_ })
    $missingNames = @($expectedNames | Where-Object { $actualNames -cnotcontains $_ })
    if ($unexpectedNames.Count -gt 0) {
        throw "$Label contains unexpected entries: $($unexpectedNames -join ', ')"
    }
    if ($missingNames.Count -gt 0) {
        throw "$Label is missing entries: $($missingNames -join ', ')"
    }
    if ($entries.Count -ne $expectedNames.Count) {
        throw "$Label must contain exactly $($expectedNames.Count) entries."
    }

    foreach ($entry in $entries) {
        $name = [string]$entry.name
        $expectedProperties = $Expected[$name]
        $actualPropertyNames = @($entry.PSObject.Properties.Name)
        $expectedPropertyNames = @($expectedProperties.Keys | ForEach-Object { [string]$_ })
        $unexpectedProperties = @($actualPropertyNames | Where-Object { $expectedPropertyNames -cnotcontains $_ })
        $missingProperties = @($expectedPropertyNames | Where-Object { $actualPropertyNames -cnotcontains $_ })
        if ($unexpectedProperties.Count -gt 0) {
            throw "$Label '$name' contains unexpected properties: $($unexpectedProperties -join ', ')"
        }
        if ($missingProperties.Count -gt 0) {
            throw "$Label '$name' is missing properties: $($missingProperties -join ', ')"
        }
        foreach ($propertyName in $expectedPropertyNames) {
            Assert-Equal `
                -Actual $entry.$propertyName `
                -Expected $expectedProperties[$propertyName] `
                -Label "$Label '$name' property '$propertyName'"
        }
    }
}

function Assert-ExactPropertyNames {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)][string[]]$ExpectedNames,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $actualNames = @($Actual.PSObject.Properties.Name)
    $unexpected = @($actualNames | Where-Object { $ExpectedNames -cnotcontains $_ })
    $missing = @($ExpectedNames | Where-Object { $actualNames -cnotcontains $_ })
    if ($unexpected.Count -gt 0) {
        throw "$Label contains unexpected properties: $($unexpected -join ', ')"
    }
    if ($missing.Count -gt 0) {
        throw "$Label is missing properties: $($missing -join ', ')"
    }
    if ($actualNames.Count -ne $ExpectedNames.Count) {
        throw "$Label property count does not match the approved manifest."
    }
}

try {
    if (-not (Test-Path -LiteralPath $ToolRoot -PathType Container)) {
        throw "Runtime tool root does not exist: $ToolRoot"
    }
    $script:ResolvedToolRoot = (Resolve-Path -LiteralPath $ToolRoot).Path

    $iperfHashes = [ordered]@{
        "iperf3/iperf3.exe" = "4aae5eee2b90c716d93bdc54c530a854596c92ff996859973b9f44e73799294e"
        "iperf3/cygwin1.dll" = "0ab76b4724499df54b75b7fa701788f1e77425ce65c8bca0a9f2120598bb8a70"
        "iperf3/cygcrypto-3.dll" = "3cfcab214b827485265c21f5c365af5055ee47ca507cc56a1422661288d51ea6"
        "iperf3/cygz.dll" = "827576482185c48ed3698454594260ee27ba32180127b8ba28c5ca68a867ce38"
        "iperf3/licenses/AR51AN_APACHE-2.0.txt" = "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
        "iperf3/licenses/CYGWIN_LGPL-3.0.txt" = "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118"
        "iperf3/licenses/CYGWIN_LINKING_EXCEPTION.txt" = "794433752103cf4bbb4a84a1bdb8fbc150abb1762704bb35fecc9f7f820be984"
        "iperf3/licenses/GPL-3.0.txt" = "0ae0485a5bd37a63e63603596417e4eb0e653334fa6c7f932ca3a0e85d4af227"
        "iperf3/licenses/IPERF3_LICENSE.txt" = "6c6e9abd761ff429c11189cd93bdee5bff7e3591253bd614b253a5f4fd30cbe5"
        "iperf3/licenses/OPENSSL_APACHE-2.0.txt" = "7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a"
        "iperf3/licenses/README.md" = "31d120a478c8d5f245b31fba5e74f9cc5960dc801907b9dee370da4157820909"
        "iperf3/licenses/ZLIB_LICENSE.txt" = "e32ff4e00d9d94930537635291da39e7e612703334bf6fde8c7f1686fe8a45a2"
        "iperf3/CORRESPONDING_SOURCE.md" = "faea146cd105ffb781c188e6b9576691cf7f4a37ba033226007b37410669e468"
    }
    $fpingHashes = [ordered]@{
        "fping/fping.exe" = "9c9ab2f26d3d32818b53ed7b664ec53546fc5cd59f4d953e06f9d3e28673f9d9"
        "fping/cygwin1.dll" = "d5562774ec1475bd1dab84c5249b273e60cc53e6aa968981414a4d6a3f8e2bfd"
        "fping/COPYING" = "6051b27e4b4a648f7bc8b329024da53a6e95ce88fcf0ccc259c371a74b741757"
        "fping/COPYING.LIB" = "1a45b1d0a8603dfe2cfc644f9dab970b1762f92babe2aac6eb2f5d4572c4a680"
        "fping/GPL-3.0.txt" = "0ae0485a5bd37a63e63603596417e4eb0e653334fa6c7f932ca3a0e85d4af227"
        "fping/CYGWIN_LICENSE" = "794433752103cf4bbb4a84a1bdb8fbc150abb1762704bb35fecc9f7f820be984"
        "fping/CYGWIN_LICENSE_NOTE.txt" = "39872eccdbdb5ed0952e2bf175532227defa3fc97fec69a96a7fef744535fbf4"
        "fping/CORRESPONDING_SOURCE.md" = "a0ca3f1e13af8ad8ae66ad5c2db7c11faba3b9392ca9c1426856ae476b9f22f3"
        "fping/BUILD_RECIPE.md" = "e1019b55830d91a97314b26985193b254507b3495f225681cc101288fa1ca1f5"
        "fping/CYGWIN_ICMP_COMPAT.patch" = "f245e88cbc111d4bc3476c1146713cc1462fff5011baf41926f2dfdabb30bf83"
    }
    $approvedFiles = @(
        "fping/BUILD_RECIPE.md",
        "fping/COPYING",
        "fping/COPYING.LIB",
        "fping/CORRESPONDING_SOURCE.md",
        "fping/CYGWIN_ICMP_COMPAT.patch",
        "fping/cygwin1.dll",
        "fping/CYGWIN_LICENSE",
        "fping/CYGWIN_LICENSE_NOTE.txt",
        "fping/fping.exe",
        "fping/GPL-3.0.txt",
        "fping/README.md",
        "fping/README.txt",
        "fping/SOURCE_PROVENANCE.json",
        "fping/VERSION.txt",
        "iperf3/CORRESPONDING_SOURCE.md",
        "iperf3/cygcrypto-3.dll",
        "iperf3/cygwin1.dll",
        "iperf3/cygz.dll",
        "iperf3/iperf3.exe",
        "iperf3/README.md",
        "iperf3/SOURCE_PROVENANCE.json",
        "iperf3/licenses/AR51AN_APACHE-2.0.txt",
        "iperf3/licenses/CYGWIN_LGPL-3.0.txt",
        "iperf3/licenses/CYGWIN_LINKING_EXCEPTION.txt",
        "iperf3/licenses/GPL-3.0.txt",
        "iperf3/licenses/IPERF3_LICENSE.txt",
        "iperf3/licenses/OPENSSL_APACHE-2.0.txt",
        "iperf3/licenses/README.md",
        "iperf3/licenses/ZLIB_LICENSE.txt"
    )
    $optionalRootFiles = @("README.md")

    $actualFiles = @(
        Get-ChildItem -LiteralPath $script:ResolvedToolRoot -Recurse -File -Force | ForEach-Object {
            $_.FullName.Substring($script:ResolvedToolRoot.Length + 1).Replace("\", "/")
        }
    )
    $unexpectedFiles = @(
        $actualFiles | Where-Object {
            $approvedFiles -notcontains $_ -and $optionalRootFiles -notcontains $_
        }
    )
    $missingApprovedFiles = @($approvedFiles | Where-Object { $actualFiles -notcontains $_ })
    if ($unexpectedFiles.Count -gt 0) {
        throw "Runtime tool directory contains unapproved files: $($unexpectedFiles -join ', ')"
    }
    if ($missingApprovedFiles.Count -gt 0) {
        throw "Runtime tool directory is incomplete: $($missingApprovedFiles -join ', ')"
    }

    foreach ($entry in $iperfHashes.GetEnumerator()) {
        Assert-FileHash -RelativePath $entry.Key -ExpectedHash $entry.Value
    }
    foreach ($entry in $fpingHashes.GetEnumerator()) {
        Assert-FileHash -RelativePath $entry.Key -ExpectedHash $entry.Value
    }

    $iperf = Read-Provenance -RelativePath "iperf3/SOURCE_PROVENANCE.json"
    Assert-ExactPropertyNames -Actual $iperf -ExpectedNames @(
        "schema_version", "component", "version", "platform", "verified_at", "distribution",
        "files", "license_files", "upstream_sources", "compliance_files",
        "corresponding_source_notice", "external_distribution_source_policy", "distributor_license_file"
    ) -Label "iPerf provenance root"
    Assert-ExactPropertyNames -Actual $iperf.distribution -ExpectedNames @(
        "repository", "tag", "tag_commit", "release_id", "release_url", "asset_name",
        "asset_id", "asset_url", "published_at", "sha256"
    ) -Label "iPerf distribution provenance"
    Assert-Equal -Actual $iperf.schema_version -Expected "netconsole.tool-provenance.v1" -Label "iPerf provenance schema"
    Assert-Equal -Actual $iperf.component -Expected "iperf3-win64-dynamic-auth" -Label "iPerf component"
    Assert-Equal -Actual $iperf.version -Expected "3.21" -Label "iPerf version"
    Assert-Equal -Actual $iperf.platform -Expected "windows-x64-cygwin" -Label "iPerf platform"
    Assert-Equal -Actual $iperf.verified_at -Expected "2026-07-18" -Label "iPerf verification date"
    Assert-Equal -Actual $iperf.distribution.repository -Expected "https://github.com/ar51an/iperf3-win-builds" -Label "iPerf distribution repository"
    Assert-Equal -Actual $iperf.distribution.tag -Expected "3.21" -Label "iPerf distribution tag"
    Assert-Equal -Actual $iperf.distribution.tag_commit -Expected "7a24a0a352b6e177993e3b6375e7d38bc8f913e8" -Label "iPerf distribution commit"
    Assert-Equal -Actual $iperf.distribution.release_id -Expected 307349802 -Label "iPerf release ID"
    Assert-Equal -Actual $iperf.distribution.release_url -Expected "https://github.com/ar51an/iperf3-win-builds/releases/tag/3.21" -Label "iPerf release URL"
    Assert-Equal -Actual $iperf.distribution.asset_name -Expected "iperf-3.21-win64-dynamic-auth.zip" -Label "iPerf distribution asset"
    Assert-Equal -Actual $iperf.distribution.asset_id -Expected 392879715 -Label "iPerf asset ID"
    Assert-Equal -Actual $iperf.distribution.asset_url -Expected "https://github.com/ar51an/iperf3-win-builds/releases/download/3.21/iperf-3.21-win64-dynamic-auth.zip" -Label "iPerf distribution URL"
    Assert-Equal -Actual $iperf.distribution.published_at -Expected "2026-04-10T01:44:57Z" -Label "iPerf release published time"
    Assert-Equal -Actual $iperf.distribution.sha256.ToLowerInvariant() -Expected "0d3ac723df5cc7b2ab1851fe9441c14291c6583b6acf8ef81dabee73c145c2eb" -Label "iPerf distribution SHA-256"
    Assert-Equal -Actual $iperf.corresponding_source_notice -Expected "CORRESPONDING_SOURCE.md" -Label "iPerf corresponding-source notice"
    Assert-Equal -Actual $iperf.external_distribution_source_policy -Expected "publish the exact corresponding source archive beside the binary release or provide a valid written offer" -Label "iPerf external source policy"
    Assert-Equal -Actual $iperf.distributor_license_file -Expected "licenses/AR51AN_APACHE-2.0.txt" -Label "iPerf distributor license"

    $iperfExpectedFiles = [ordered]@{
        "iperf3.exe" = [ordered]@{
            name = "iperf3.exe"; version = "3.21"; sha256 = $iperfHashes["iperf3/iperf3.exe"]
        }
        "cygwin1.dll" = [ordered]@{
            name = "cygwin1.dll"; version = "3.6.7-1"; sha256 = $iperfHashes["iperf3/cygwin1.dll"]
        }
        "cygcrypto-3.dll" = [ordered]@{
            name = "cygcrypto-3.dll"; version = "3.0.19"; sha256 = $iperfHashes["iperf3/cygcrypto-3.dll"]
        }
        "cygz.dll" = [ordered]@{
            name = "cygz.dll"; version = "1.3.2"; sha256 = $iperfHashes["iperf3/cygz.dll"]
        }
    }
    Assert-ExactNamedEntries -Items @($iperf.files) -Expected $iperfExpectedFiles -Label "iPerf provenance files"

    $iperfExpectedLicenses = [ordered]@{}
    foreach ($name in @(
        "AR51AN_APACHE-2.0.txt",
        "CYGWIN_LGPL-3.0.txt",
        "GPL-3.0.txt",
        "CYGWIN_LINKING_EXCEPTION.txt",
        "IPERF3_LICENSE.txt",
        "OPENSSL_APACHE-2.0.txt",
        "ZLIB_LICENSE.txt"
    )) {
        $iperfExpectedLicenses[$name] = [ordered]@{
            name = $name; sha256 = $iperfHashes["iperf3/licenses/$name"]
        }
    }
    Assert-ExactNamedEntries -Items @($iperf.license_files) -Expected $iperfExpectedLicenses -Label "iPerf provenance license files"

    $iperfExpectedCompliance = [ordered]@{
        "CORRESPONDING_SOURCE.md" = [ordered]@{
            name = "CORRESPONDING_SOURCE.md"; sha256 = $iperfHashes["iperf3/CORRESPONDING_SOURCE.md"]
        }
        "licenses/README.md" = [ordered]@{
            name = "licenses/README.md"; sha256 = $iperfHashes["iperf3/licenses/README.md"]
        }
    }
    Assert-ExactNamedEntries -Items @($iperf.compliance_files) -Expected $iperfExpectedCompliance -Label "iPerf provenance compliance files"

    $iperfExpectedSources = [ordered]@{
        "iperf3" = [ordered]@{
            name = "iperf3"
            version = "3.21"
            repository = "https://github.com/esnet/iperf"
            tag = "3.21"
            tag_object = "ec66336d2c152bf964f671e9e20a11de05edb239"
            tag_commit = "d39cf41526626b4e5a130f115d931cd6cbdffc19"
            license_file = "licenses/IPERF3_LICENSE.txt"
        }
        "Cygwin Runtime" = [ordered]@{
            name = "Cygwin Runtime"
            version = "3.6.7-1"
            source_package = "cygwin-3.6.7-1-src"
            source_index = "https://cygwin.com/packages/summary/cygwin-src.html"
            source_contents = "https://cygwin.com/packages/src/cygwin-src/cygwin-3.6.7-1-src"
            source_archive_path = "src/release/cygwin/cygwin-3.6.7-1-src.tar.xz"
            source_archive_size = 9309160
            source_archive_sha512 = "82a190c3516511af7d1305e1bcd4aa0177c1fb584b6468a887a9119565bccd88630b2a3b826d902983a83adefb11545346dcf27616186304d6c66879e1647335"
            license_file = "licenses/CYGWIN_LGPL-3.0.txt"
            gpl_file = "licenses/GPL-3.0.txt"
            exception_file = "licenses/CYGWIN_LINKING_EXCEPTION.txt"
        }
        "OpenSSL Cygwin Runtime" = [ordered]@{
            name = "OpenSSL Cygwin Runtime"
            version = "3.0.19-1"
            source_index = "https://cygwin.com/packages/summary/openssl-src.html"
            license_file = "licenses/OPENSSL_APACHE-2.0.txt"
        }
        "zlib Cygwin Runtime" = [ordered]@{
            name = "zlib Cygwin Runtime"
            version = "1.3.2-1"
            source_index = "https://cygwin.com/packages/summary/zlib-src.html"
            license_file = "licenses/ZLIB_LICENSE.txt"
        }
    }
    Assert-ExactNamedEntries -Items @($iperf.upstream_sources) -Expected $iperfExpectedSources -Label "iPerf provenance upstream sources"

    $fping = Read-Provenance -RelativePath "fping/SOURCE_PROVENANCE.json"
    Assert-ExactPropertyNames -Actual $fping -ExpectedNames @(
        "schema_version", "component", "version", "platform", "verified_at", "build", "files",
        "license_files", "compliance_files", "upstream_sources", "corresponding_source_notice",
        "external_distribution_source_policy"
    ) -Label "fping provenance root"
    Assert-ExactPropertyNames -Actual $fping.build -ExpectedNames @(
        "method", "built_at", "git_describe_at_build", "source_state", "configure_args",
        "patch_file", "patch_sha256", "recipe_file", "recipe_sha256",
        "network_required_during_product_packaging"
    ) -Label "fping build provenance"
    Assert-Equal -Actual $fping.schema_version -Expected "netconsole.tool-provenance.v1" -Label "fping provenance schema"
    Assert-Equal -Actual $fping.component -Expected "fping-windows-x64-cygwin" -Label "fping component"
    Assert-Equal -Actual $fping.version -Expected "5.5" -Label "fping version"
    Assert-Equal -Actual $fping.platform -Expected "windows-x64-cygwin" -Label "fping platform"
    Assert-Equal -Actual $fping.verified_at -Expected "2026-07-18" -Label "fping verification date"
    Assert-Equal -Actual $fping.build.method -Expected "local Cygwin x86_64 build" -Label "fping build method"
    Assert-Equal -Actual $fping.build.built_at -Expected "2026-06-27T00:28:00+08:00" -Label "fping build time"
    Assert-Equal -Actual $fping.build.source_state -Expected "upstream v5.5 plus archived Cygwin ICMP compatibility patch" -Label "fping build source state"
    Assert-Equal -Actual $fping.build.network_required_during_product_packaging -Expected $false -Label "fping offline packaging flag"
    Assert-Equal -Actual $fping.corresponding_source_notice -Expected "CORRESPONDING_SOURCE.md" -Label "fping corresponding-source notice"
    Assert-Equal -Actual $fping.external_distribution_source_policy -Expected "publish the exact corresponding source archive beside the binary release or provide a valid written offer" -Label "fping external source policy"
    Assert-Equal -Actual $fping.build.git_describe_at_build -Expected "v5.5-dirty" -Label "fping build source state"
    Assert-Equal -Actual $fping.build.patch_file -Expected "CYGWIN_ICMP_COMPAT.patch" -Label "fping build patch"
    Assert-Equal -Actual $fping.build.patch_sha256 -Expected $fpingHashes["fping/CYGWIN_ICMP_COMPAT.patch"] -Label "fping build patch SHA-256"
    Assert-Equal -Actual $fping.build.recipe_file -Expected "BUILD_RECIPE.md" -Label "fping build recipe"
    Assert-Equal -Actual $fping.build.recipe_sha256 -Expected $fpingHashes["fping/BUILD_RECIPE.md"] -Label "fping build recipe SHA-256"
    $configureArgs = @($fping.build.configure_args)
    if ($configureArgs.Count -ne 2 -or $configureArgs[0] -cne "--disable-ipv6" -or $configureArgs[1] -cne "--enable-safe-limits") {
        throw "fping configure_args must be exactly '--disable-ipv6', '--enable-safe-limits'."
    }

    $fpingExpectedFiles = [ordered]@{
        "fping.exe" = [ordered]@{
            name = "fping.exe"; version = "5.5"; sha256 = $fpingHashes["fping/fping.exe"]
        }
        "cygwin1.dll" = [ordered]@{
            name = "cygwin1.dll"; version = "3.6.9-1"; sha256 = $fpingHashes["fping/cygwin1.dll"]
        }
    }
    Assert-ExactNamedEntries -Items @($fping.files) -Expected $fpingExpectedFiles -Label "fping provenance files"

    $fpingExpectedLicenses = [ordered]@{}
    foreach ($name in @("COPYING", "COPYING.LIB", "GPL-3.0.txt", "CYGWIN_LICENSE", "CYGWIN_LICENSE_NOTE.txt")) {
        $fpingExpectedLicenses[$name] = [ordered]@{
            name = $name; sha256 = $fpingHashes["fping/$name"]
        }
    }
    Assert-ExactNamedEntries -Items @($fping.license_files) -Expected $fpingExpectedLicenses -Label "fping provenance license files"

    $fpingExpectedCompliance = [ordered]@{}
    foreach ($name in @("CORRESPONDING_SOURCE.md", "BUILD_RECIPE.md", "CYGWIN_ICMP_COMPAT.patch")) {
        $fpingExpectedCompliance[$name] = [ordered]@{
            name = $name; sha256 = $fpingHashes["fping/$name"]
        }
    }
    Assert-ExactNamedEntries -Items @($fping.compliance_files) -Expected $fpingExpectedCompliance -Label "fping provenance compliance files"

    $fpingExpectedSources = [ordered]@{
        "fping" = [ordered]@{
            name = "fping"
            version = "5.5"
            repository = "https://github.com/schweikert/fping"
            tag = "v5.5"
            tag_commit = "06f9481ef3cf79c2aa973718366fb13927777689"
        }
        "Cygwin Runtime" = [ordered]@{
            name = "Cygwin Runtime"
            version = "3.6.9-1"
            source_package = "cygwin-3.6.9-1-src"
            source_index = "https://cygwin.com/packages/summary/cygwin-src.html"
            source_contents = "https://cygwin.com/packages/src/cygwin-src/cygwin-3.6.9-1-src"
            source_archive_path = "src/release/cygwin/cygwin-3.6.9-1-src.tar.xz"
            source_archive_size = 9312760
            source_archive_sha512 = "771ab64fff17323a32b7cb56140c974d446899a5d4eb5b76115e14cd8fe2e4108be5f30112e441def0f86666d37ab35ba5fb31950910d91ffc12ba69e0934f6e"
            repository = "https://cygwin.com/git/newlib-cygwin.git"
            tag = "cygwin-3.6.9"
            tag_object = "f802d89cdc3fbbfbb47f5a6b3a4e27b7a2363795"
            tag_commit = "daabea98682f3f4bef0044829a8d24226135bb71"
        }
    }
    Assert-ExactNamedEntries -Items @($fping.upstream_sources) -Expected $fpingExpectedSources -Label "fping provenance upstream sources"

    Write-Host "[OK] Runtime tools validated from local files only: $script:ResolvedToolRoot"
    exit 0
}
catch {
    Write-Error "[ERROR] Runtime tool validation failed: $($_.Exception.Message)"
    exit 1
}
