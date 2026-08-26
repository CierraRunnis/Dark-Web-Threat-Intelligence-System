[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Position = 0)]
    [ValidateSet("status", "plan", "apply", "migrate", "cleanup", "first-run")]
    [string]$Action = "status",

    [string]$DataRoot = "",

    [ValidateRange(1, 1024)]
    [int]$MinimumFreeGiB = 20,

    [switch]$NoRestart,
    [switch]$Force,

    [ValidateSet("User", "Process")]
    [string]$EnvironmentTarget = "User"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CollectorRoot = [IO.Path]::GetFullPath((Join-Path $ScriptDir ".."))
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $CollectorRoot ".."))
$Launcher = Join-Path $ScriptDir "start_all_services_windows.ps1"
$LocalAppDataRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $env:USERPROFILE "AppData\Local" }
$ControlRoot = Join-Path $LocalAppDataRoot "DarkWebThreatIntel"
$UpdateStateRoot = [string][Environment]::GetEnvironmentVariable("DARKWEB_UPDATE_STATE_DIR", "User")
if (-not $UpdateStateRoot) { $UpdateStateRoot = [string]$env:DARKWEB_UPDATE_STATE_DIR }
if (-not $UpdateStateRoot) { $UpdateStateRoot = $ControlRoot }
if (-not [IO.Path]::IsPathRooted($UpdateStateRoot)) { throw "DARKWEB_UPDATE_STATE_DIR must be an absolute local path" }
$UpdateStateRoot = [IO.Path]::GetFullPath($UpdateStateRoot)
if ($UpdateStateRoot.StartsWith("\\", [StringComparison]::Ordinal)) { throw "DARKWEB_UPDATE_STATE_DIR does not support network or WSL UNC paths" }
$InstallationStatePath = Join-Path $UpdateStateRoot "installation.json"
$installation = $null
if (Test-Path -LiteralPath $InstallationStatePath -PathType Leaf) {
    $installation = Get-Content -LiteralPath $InstallationStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$installation.format -ne 1 -or -not $installation.current_root) {
        throw "Managed installation state is invalid: $InstallationStatePath"
    }
    $activeProjectRoot = [IO.Path]::GetFullPath([string]$installation.current_root).TrimEnd("\")
    if ($activeProjectRoot -ine $ProjectRoot.TrimEnd("\")) {
        $activeScript = Join-Path $activeProjectRoot "darkweb_collector\scripts\configure_data_root_windows.ps1"
        if (-not (Test-Path -LiteralPath $activeScript -PathType Leaf)) {
            throw "Active release data-root configurator was not found: $activeScript"
        }
        $forward = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $activeScript, $Action)
        if ($DataRoot) { $forward += @("-DataRoot", $DataRoot) }
        $forward += @("-MinimumFreeGiB", [string]$MinimumFreeGiB)
        if ($EnvironmentTarget -ne "User") { $forward += @("-EnvironmentTarget", $EnvironmentTarget) }
        if ($NoRestart) { $forward += "-NoRestart" }
        if ($Force) { $forward += "-Force" }
        if ($WhatIfPreference) { $forward += "-WhatIf" }
        & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" @forward
        exit $LASTEXITCODE
    }
}
$ConfigPath = Join-Path $ControlRoot "data-root.json"
$CopyManifestPath = Join-Path $ControlRoot "data-root-copy-manifest.json"
$RuntimePortsPath = Join-Path $CollectorRoot ".runtime\windows\ports.json"
$RuntimeServicesPath = Join-Path $CollectorRoot ".runtime\windows\services.json"
$ManagedEnvironment = @(
    "DARKWEB_DATA_ROOT",
    "DARKWEB_USER_DATA_ROOT",
    "DARKWEB_APP_ROOT",
    "DARKWEB_MIGRATION_ROOT",
    "DARKWEB_ACTIVE_RELEASE_FILE",
    "DARKWEB_COLLECTOR_DB_PATH",
    "DARKWEB_COLLECTOR_SITES_FILE",
    "DARKWEB_GARNET_DATA_ROOT",
    "DARKWEB_AUTH_PASSWORD_FILE",
    "DARKWEB_COLLECTOR_OUTPUT_ROOT",
    "DARKWEB_TOR_EXPERT_DIR",
    "DARKWEB_TOR_EXECUTABLE",
    "DARKWEB_TOR_TRANSPORT_EXECUTABLE",
    "DARKWEB_TOR_PT_CONFIG_PATH",
    "PLAYWRIGHT_BROWSERS_PATH"
)

function Write-Info([string]$Message) { Write-Host "[INFO] $Message" }
function Write-Warn([string]$Message) { Write-Host "[WARN] $Message" -ForegroundColor Yellow }

function Resolve-SafeDataRoot([string]$Value) {
    if (-not $Value) { throw "DataRoot is required" }
    $expanded = [Environment]::ExpandEnvironmentVariables($Value)
    if (-not [IO.Path]::IsPathRooted($expanded)) {
        throw "DataRoot must be an absolute path below a drive root"
    }
    $resolved = [IO.Path]::GetFullPath($expanded)
    if ($resolved.StartsWith("\\", [StringComparison]::Ordinal)) {
        throw "DataRoot must be on a local Windows volume; network and WSL UNC paths are not supported"
    }
    $driveRoot = [IO.Path]::GetPathRoot($resolved).TrimEnd("\")
    if ($resolved.TrimEnd("\") -ieq $driveRoot) {
        throw "DataRoot cannot be a drive root; use a dedicated directory such as D:\DarkWebThreatIntel"
    }
    foreach ($protected in @($env:SystemRoot, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $protected) { continue }
        $protectedPath = [IO.Path]::GetFullPath($protected).TrimEnd("\")
        $protectedPrefix = $protectedPath + "\"
        if ($resolved.TrimEnd("\") -ieq $protectedPath -or
            $resolved.TrimEnd("\").StartsWith($protectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "DataRoot cannot be under a protected system directory: $protectedPath"
        }
    }
    return $resolved.TrimEnd("\")
}

function Read-ConfiguredDataRoot {
    $targetValue = [string][Environment]::GetEnvironmentVariable("DARKWEB_DATA_ROOT", $EnvironmentTarget)
    if ($targetValue) { return Resolve-SafeDataRoot $targetValue }
    if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
        $payload = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([int]$payload.format -ne 1 -or -not $payload.data_root) {
            throw "Data root configuration is invalid: $ConfigPath"
        }
        return Resolve-SafeDataRoot ([string]$payload.data_root)
    }
    $processValue = [string]$env:DARKWEB_DATA_ROOT
    if ($processValue) { return Resolve-SafeDataRoot $processValue }
    return [IO.Path]::GetFullPath($ControlRoot)
}

function Get-EffectiveEnvironmentValue([string]$Name) {
    if ($EnvironmentTarget -eq "User") {
        $userValue = [string][Environment]::GetEnvironmentVariable($Name, "User")
        if ($userValue) { return $userValue }
    }
    $processValue = [string][Environment]::GetEnvironmentVariable($Name, "Process")
    if ($processValue) { return $processValue }
    if ($EnvironmentTarget -eq "User") {
        return [string][Environment]::GetEnvironmentVariable($Name, "User")
    }
    return ""
}

function Resolve-RebasedPath([string]$Value, [string]$SourceRoot, [string]$TargetRoot, [string]$DefaultRelativePath) {
    if (-not $Value) {
        if (-not $DefaultRelativePath) { return "" }
        return Join-Path $TargetRoot $DefaultRelativePath
    }
    $fullValue = [IO.Path]::GetFullPath($Value).TrimEnd("\")
    $fullSource = [IO.Path]::GetFullPath($SourceRoot).TrimEnd("\")
    if ($fullValue -ieq $fullSource) { return $TargetRoot }
    $sourcePrefix = $fullSource + "\"
    if ($fullValue.StartsWith($sourcePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        return Join-Path $TargetRoot $fullValue.Substring($sourcePrefix.Length)
    }
    return $fullValue
}

function Write-DataRootConfig([string]$Root, [string]$PreviousRoot = "", [bool]$PreviousCleaned = $false) {
    New-Item -ItemType Directory -Path $ControlRoot -Force | Out-Null
    $temporary = "$ConfigPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    $payload = [ordered]@{
        format = 1
        data_root = $Root
        previous_data_root = $PreviousRoot
        previous_data_cleaned = $PreviousCleaned
        configured_at = [DateTimeOffset]::UtcNow.ToString("o")
    }
    try {
        $payload | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $ConfigPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Read-PreviousDataRoot {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { return "" }
    $payload = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$payload.format -ne 1) { throw "Data root configuration is invalid: $ConfigPath" }
    if (-not $payload.previous_data_root -or $payload.previous_data_cleaned) { return "" }
    return Resolve-SafeDataRoot ([string]$payload.previous_data_root)
}

function Get-ExistingParent([string]$Path) {
    $candidate = [IO.Path]::GetFullPath($Path)
    while (-not (Test-Path -LiteralPath $candidate) -and $candidate -ne [IO.Path]::GetPathRoot($candidate)) {
        $candidate = Split-Path -Parent $candidate
    }
    return $candidate
}

function Get-FreeBytes([string]$Path) {
    $parent = Get-ExistingParent $Path
    return [int64]([IO.DriveInfo]::new([IO.Path]::GetPathRoot($parent))).AvailableFreeSpace
}

function Test-DataRootConfigured {
    if ([Environment]::GetEnvironmentVariable("DARKWEB_DATA_ROOT", $EnvironmentTarget)) { return $true }
    if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) { return $true }
    if ($env:DARKWEB_DATA_ROOT -or $env:DARKWEB_USER_DATA_ROOT) { return $true }
    return $false
}

function Select-FirstRunDataRoot {
    $drives = @(
        [IO.DriveInfo]::GetDrives() |
            Where-Object { $_.IsReady -and $_.DriveType -eq [IO.DriveType]::Fixed } |
            Sort-Object Name
    )
    if ($drives.Count -eq 0) { throw "No ready local fixed drive was found" }

    $controlDrive = [IO.Path]::GetPathRoot($ControlRoot).TrimEnd("\")
    $defaultDrive = $drives | Where-Object { $_.Name.TrimEnd("\") -ieq $controlDrive } | Select-Object -First 1
    if (-not $defaultDrive) { $defaultDrive = $drives[0] }

    Write-Host ""
    Write-Host "First-time setup: choose where application releases and data will be stored."
    foreach ($drive in $drives) {
        $driveName = $drive.Name.TrimEnd("\")
        $target = if ($driveName -ieq $controlDrive) { $ControlRoot } else { Join-Path $drive.Name "DarkWebThreatIntel" }
        Write-Host ("  {0}  {1:N1} GiB free  ->  {2}" -f $driveName, ($drive.AvailableFreeSpace / 1GB), $target)
    }

    $defaultName = $defaultDrive.Name.TrimEnd("\")
    $answer = (Read-Host "Enter a drive letter [$defaultName], or Q to cancel").Trim()
    if (-not $answer) { $answer = $defaultName }
    if ($answer -ieq "Q") { throw "First-time setup was cancelled" }
    if ($answer -notmatch "^[A-Za-z]:?$") { throw "Enter one of the listed drive letters" }

    $selectedName = $answer.Substring(0, 1).ToUpperInvariant() + ":"
    $selectedDrive = $drives | Where-Object { $_.Name.TrimEnd("\") -ieq $selectedName } | Select-Object -First 1
    if (-not $selectedDrive) { throw "Drive $selectedName is not a ready local fixed drive" }
    if ($selectedName -ieq $controlDrive) { return [IO.Path]::GetFullPath($ControlRoot).TrimEnd("\") }
    return [IO.Path]::GetFullPath((Join-Path $selectedDrive.Name "DarkWebThreatIntel")).TrimEnd("\")
}

function Test-PathUnder([string]$Path, [string]$Root) {
    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd("\")
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd("\")
    return $fullPath.StartsWith($fullRoot + "\", [StringComparison]::OrdinalIgnoreCase)
}

function Test-ProjectRunning {
    if (-not (Test-Path -LiteralPath $RuntimePortsPath -PathType Leaf)) { return $false }
    try {
        $ports = Get-Content -LiteralPath $RuntimePortsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$([int]$ports.api_port)/api/health" -TimeoutSec 3
        return $response.StatusCode -eq 200
    }
    catch {
    }
    if (Test-Path -LiteralPath $RuntimeServicesPath -PathType Leaf) {
        try {
            $records = @(Get-Content -LiteralPath $RuntimeServicesPath -Raw -Encoding UTF8 | ConvertFrom-Json)
            foreach ($record in $records) {
                if ($record.pid -and (Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue)) {
                    return $true
                }
            }
        }
        catch {
        }
    }
    return $false
}

$ManagedDataFiles = @(
    "collector.db",
    "collector.db-wal",
    "collector.db-shm",
    "collector.db-journal",
    "active-release.json",
    "auth-password.txt",
    "garnet-runtime.json"
)
$ManagedDataDirectories = @(
    "output",
    "migrations",
    "config",
    "secrets",
    "update-backups",
    "garnet-data",
    "tor-expert",
    "tor_bridge_runtime",
    "tor_bridge_runtime_auto",
    "runtimes",
    "npm-cache",
    "playwright"
)

function Get-ManagedFiles([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return @() }
    $files = [System.Collections.Generic.List[System.IO.FileInfo]]::new()
    foreach ($name in $ManagedDataFiles) {
        $itemPath = Join-Path $Root $name
        if (-not (Test-Path -LiteralPath $itemPath -PathType Leaf)) { continue }
        $item = Get-Item -LiteralPath $itemPath -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Managed data file is a reparse point and cannot be copied safely: $($item.FullName)"
        }
        $files.Add($item)
    }
    foreach ($name in $ManagedDataDirectories) {
        $directoryPath = Join-Path $Root $name
        if (-not (Test-Path -LiteralPath $directoryPath -PathType Container)) { continue }
        $directory = Get-Item -LiteralPath $directoryPath -Force -ErrorAction Stop
        if (($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Managed data directory is a reparse point and cannot be copied safely: $($directory.FullName)"
        }
        foreach ($child in Get-ChildItem -LiteralPath $directory.FullName -Recurse -Force -ErrorAction Stop) {
            if (($child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Data root contains a reparse point and cannot be copied safely: $($child.FullName)"
            }
            if (-not $child.PSIsContainer) {
                $files.Add($child)
            }
        }
    }
    return @($files)
}

function Get-ManagedBytes([string]$Root) {
    $measure = (@(Get-ManagedFiles $Root) | Measure-Object -Property Length -Sum)
    if ($null -eq $measure) { return [int64]0 }
    if ($null -eq $measure.Sum) { return [int64]0 }
    return [int64]$measure.Sum
}

function Assert-Capacity([string]$Target, [int64]$CopyBytes) {
    $required = [Math]::Max([int64]$MinimumFreeGiB * 1GB, [int64]($CopyBytes * 1.20))
    $free = Get-FreeBytes $Target
    if ($free -lt $required -and -not $Force) {
        throw "Insufficient free space at $Target. Required $([Math]::Round($required / 1GB, 2)) GiB, available $([Math]::Round($free / 1GB, 2)) GiB"
    }
    Write-Info "Capacity check: $([Math]::Round($free / 1GB, 2)) GiB free; $([Math]::Round($required / 1GB, 2)) GiB required"
}

function Copy-AndVerifyData([string]$Source, [string]$Target) {
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    foreach ($name in $ManagedDataDirectories) {
        $sourceDirectory = Join-Path $Source $name
        if (Test-Path -LiteralPath $sourceDirectory -PathType Container) {
            New-Item -ItemType Directory -Path (Join-Path $Target $name) -Force | Out-Null
        }
    }
    $files = @(Get-ManagedFiles $Source)
    $manifestEntries = [System.Collections.Generic.List[object]]::new()
    $index = 0
    foreach ($file in $files) {
        $index++
        $relative = $file.FullName.Substring($Source.TrimEnd("\").Length).TrimStart("\")
        $destination = Join-Path $Target $relative
        $destinationParent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        $sourceHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            $existing = Get-Item -LiteralPath $destination
            if ($existing.Length -eq $file.Length -and
                (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -eq $sourceHash) {
                $manifestEntries.Add([ordered]@{ path = $relative; size = [int64]$file.Length; sha256 = $sourceHash.ToLowerInvariant() })
                continue
            }
            throw "Target contains a different file at $relative; choose an empty directory"
        }
        $temporary = "$destination.copy-$PID"
        Copy-Item -LiteralPath $file.FullName -Destination $temporary -Force
        if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash -ne $sourceHash -or
            (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne $sourceHash) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
            throw "Copy verification failed: $relative"
        }
        Move-Item -LiteralPath $temporary -Destination $destination -Force
        $manifestEntries.Add([ordered]@{ path = $relative; size = [int64]$file.Length; sha256 = $sourceHash.ToLowerInvariant() })
        if ($index % 250 -eq 0) { Write-Info "Copied and verified $index/$($files.Count) files" }
    }
    foreach ($entry in $manifestEntries) {
        $sourcePath = Join-Path $Source ([string]$entry.path)
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf) -or
            (Get-Item -LiteralPath $sourcePath).Length -ne [int64]$entry.size -or
            (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne [string]$entry.sha256) {
            throw "Source data changed during migration; the target was not activated"
        }
    }
    $script:CopyManifestEntries = @($manifestEntries)
    Write-Info "Copied and verified $($files.Count) files"
}

function Write-CopyManifest([string]$Source, [string]$Target) {
    New-Item -ItemType Directory -Path $ControlRoot -Force | Out-Null
    $temporary = "$CopyManifestPath.tmp-$PID"
    $payload = [ordered]@{
        format = 1
        source_root = $Source
        target_root = $Target
        verified_at = [DateTimeOffset]::UtcNow.ToString("o")
        entries = @($script:CopyManifestEntries)
    }
    try {
        $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $CopyManifestPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Read-CopyManifest([string]$Source, [string]$Target) {
    if (-not (Test-Path -LiteralPath $CopyManifestPath -PathType Leaf)) {
        throw "Verified copy manifest is missing: $CopyManifestPath"
    }
    $payload = Get-Content -LiteralPath $CopyManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$payload.format -ne 1 -or
        [IO.Path]::GetFullPath([string]$payload.source_root).TrimEnd("\") -ine $Source.TrimEnd("\") -or
        [IO.Path]::GetFullPath([string]$payload.target_root).TrimEnd("\") -ine $Target.TrimEnd("\")) {
        throw "Verified copy manifest does not match the recorded data roots"
    }
    return $payload
}

function Remove-VerifiedPreviousData([string]$Source, [string]$Target) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Previous data root does not exist: $Source"
    }
    $manifest = Read-CopyManifest $Source $Target
    $expected = @{}
    foreach ($entry in @($manifest.entries)) {
        $relative = [string]$entry.path
        if (-not $relative -or $expected.ContainsKey($relative)) { throw "Verified copy manifest contains an invalid path" }
        $expected[$relative] = $entry
    }
    $files = @(Get-ManagedFiles $Source)
    if ($files.Count -ne $expected.Count) {
        throw "Cleanup stopped because the previous data root changed after migration"
    }
    $changedTargets = 0
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($Source.TrimEnd("\").Length).TrimStart("\")
        if (-not $expected.ContainsKey($relative)) {
            throw "Cleanup stopped because an unverified old file exists: $relative"
        }
        $entry = $expected[$relative]
        $sourceHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ([int64]$entry.size -ne $file.Length -or [string]$entry.sha256 -cne $sourceHash) {
            throw "Cleanup stopped because the old source changed after migration: $relative"
        }
        $destination = Join-Path $Target $relative
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
            throw "Cleanup stopped because the verified target file is missing: $relative"
        }
        $targetHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($targetHash -cne [string]$entry.sha256) {
            $changedTargets++
        }
    }
    if (-not $Force) {
        $answer = Read-Host "Verified $($files.Count) old files against the migration manifest ($changedTargets target files changed after switch). Type CLEANUP to remove only the verified old files from $Source"
        if ($answer -cne "CLEANUP") { throw "Cleanup cancelled; no old data was removed" }
    }
    foreach ($file in $files) {
        Remove-Item -LiteralPath $file.FullName -Force
    }
    $directories = [System.Collections.Generic.List[System.IO.DirectoryInfo]]::new()
    foreach ($name in $ManagedDataDirectories) {
        $topLevelPath = Join-Path $Source $name
        if (-not (Test-Path -LiteralPath $topLevelPath -PathType Container)) { continue }
        $topLevel = Get-Item -LiteralPath $topLevelPath -Force -ErrorAction Stop
        $directories.Add($topLevel)
        foreach ($child in Get-ChildItem -LiteralPath $topLevel.FullName -Recurse -Directory -Force -ErrorAction Stop) {
            $directories.Add($child)
        }
    }
    foreach ($directory in $directories | Sort-Object { $_.FullName.Length } -Descending) {
        if (@(Get-ChildItem -LiteralPath $directory.FullName -Force).Count -eq 0) {
            Remove-Item -LiteralPath $directory.FullName -Force
        }
    }
    Write-Info "Removed $($files.Count) verified old data files; control files and PostgreSQL data were preserved"
}

function Convert-RebasedMetadataValue($Value, [string]$Source, [string]$Target, [ref]$Changed) {
    if ($Value -is [string]) {
        $sourceRoot = $Source.TrimEnd("\")
        if ($Value -ieq $sourceRoot) {
            $Changed.Value = $true
            return $Target.TrimEnd("\")
        }
        if ($Value.StartsWith($sourceRoot + "\", [StringComparison]::OrdinalIgnoreCase)) {
            $Changed.Value = $true
            return $Target.TrimEnd("\") + $Value.Substring($sourceRoot.Length)
        }
        return $Value
    }
    if ($Value -is [System.Collections.IList]) {
        for ($index = 0; $index -lt $Value.Count; $index++) {
            $Value[$index] = Convert-RebasedMetadataValue $Value[$index] $Source $Target $Changed
        }
        return $Value
    }
    if ($Value -is [pscustomobject]) {
        foreach ($property in $Value.PSObject.Properties) {
            $property.Value = Convert-RebasedMetadataValue $property.Value $Source $Target $Changed
        }
    }
    return $Value
}

function Update-InstallationDataPaths([string]$Source, [string]$Target) {
    $path = $InstallationStatePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return }
    $payload = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$payload.format -ne 1) { throw "Managed installation state is invalid: $path" }
    $changed = $false

    function Resolve-InstallationDataPath([string]$Name, [string]$Value) {
        if (-not $Value) { return $Value }
        $fullValue = [IO.Path]::GetFullPath($Value).TrimEnd("\")
        $sourceRoot = [IO.Path]::GetFullPath($Source).TrimEnd("\")
        $allowedRoots = switch ($Name) {
            "sites_file" { @((Join-Path $sourceRoot "config")) }
            "output_root" { @((Join-Path $sourceRoot "output"), (Join-Path $sourceRoot "migrations")) }
            "data_root" { @($sourceRoot) }
            default { @() }
        }
        $allowed = $false
        foreach ($allowedRoot in $allowedRoots) {
            $normalizedRoot = [IO.Path]::GetFullPath($allowedRoot).TrimEnd("\")
            if ($fullValue -ieq $normalizedRoot -or
                $fullValue.StartsWith($normalizedRoot + "\", [StringComparison]::OrdinalIgnoreCase)) {
                $allowed = $true
                break
            }
        }
        if (-not $allowed) { return $fullValue }
        $rebased = Resolve-RebasedPath $fullValue $sourceRoot $Target ""
        if ((Test-Path -LiteralPath $fullValue) -and -not (Test-Path -LiteralPath $rebased)) {
            throw "Managed installation $Name was not copied to the target data root: $rebased"
        }
        return $rebased
    }

    foreach ($name in @("sites_file", "output_root", "data_root")) {
        $property = $payload.PSObject.Properties[$name]
        if (-not $property -or -not [string]$property.Value) { continue }
        $rebased = Resolve-InstallationDataPath $name ([string]$property.Value)
        if ($rebased -ine [string]$property.Value) {
            $property.Value = $rebased
            $changed = $true
        }
    }
    $previousProperty = $payload.PSObject.Properties["previous"]
    if ($previousProperty -and $previousProperty.Value) {
        foreach ($name in @("sites_file", "output_root", "data_root")) {
            $property = $previousProperty.Value.PSObject.Properties[$name]
            if (-not $property -or -not [string]$property.Value) { continue }
            $rebased = Resolve-InstallationDataPath $name ([string]$property.Value)
            if ($rebased -ine [string]$property.Value) {
                $property.Value = $rebased
                $changed = $true
            }
        }
    }
    if (-not $changed) { return }
    $temporary = "$path.tmp-$PID"
    $payload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $path -Force
}

function Update-MigrationMetadata([string]$Source, [string]$Target) {
    $targetActiveRelease = Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_ACTIVE_RELEASE_FILE") $Source $Target "active-release.json"
    $targetMigrationRoot = Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_MIGRATION_ROOT") $Source $Target "migrations"
    $metadata = [System.Collections.Generic.List[string]]::new()
    if ((Test-PathUnder $targetActiveRelease $Target) -or [IO.Path]::GetFullPath($targetActiveRelease).TrimEnd("\") -ieq $Target.TrimEnd("\")) {
        $metadata.Add($targetActiveRelease)
    }
    if (((Test-PathUnder $targetMigrationRoot $Target) -or [IO.Path]::GetFullPath($targetMigrationRoot).TrimEnd("\") -ieq $Target.TrimEnd("\")) -and
        (Test-Path -LiteralPath $targetMigrationRoot -PathType Container)) {
        foreach ($path in Get-ChildItem -LiteralPath $targetMigrationRoot -Recurse -File -ErrorAction Stop |
            Where-Object { $_.Name -in @("state.json", "import-report.json", "previous-active-release.json") } |
            Select-Object -ExpandProperty FullName) {
            $metadata.Add($path)
        }
    }
    foreach ($path in $metadata | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }) {
        $payload = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $changed = $false
        $payload = Convert-RebasedMetadataValue $payload $Source $Target ([ref]$changed)
        if (-not $changed) { continue }
        $temporary = "$path.tmp-$PID"
        $payload | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $path -Force
    }
    Update-InstallationDataPaths $Source $Target
}

function Set-ManagedEnvironment([string]$Root, [string]$SourceRoot) {
    $activePath = Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_ACTIVE_RELEASE_FILE") $SourceRoot $Root "active-release.json"
    $outputPath = Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_COLLECTOR_OUTPUT_ROOT") $SourceRoot $Root "output"
    if (Test-Path -LiteralPath $activePath -PathType Leaf) {
        try {
            $active = Get-Content -LiteralPath $activePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($active.output_root) { $outputPath = [string]$active.output_root }
        }
        catch { throw "Copied active release configuration is invalid: $activePath" }
    }
    $values = [ordered]@{
        DARKWEB_DATA_ROOT = $Root
        DARKWEB_USER_DATA_ROOT = $Root
        DARKWEB_APP_ROOT = (Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_APP_ROOT") $SourceRoot $Root "app")
        DARKWEB_MIGRATION_ROOT = (Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_MIGRATION_ROOT") $SourceRoot $Root "migrations")
        DARKWEB_ACTIVE_RELEASE_FILE = $activePath
        DARKWEB_COLLECTOR_DB_PATH = (Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_COLLECTOR_DB_PATH") $SourceRoot $Root "collector.db")
        DARKWEB_COLLECTOR_SITES_FILE = (Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_COLLECTOR_SITES_FILE") $SourceRoot $Root "")
        DARKWEB_GARNET_DATA_ROOT = (Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_GARNET_DATA_ROOT") $SourceRoot $Root "garnet-data")
        DARKWEB_AUTH_PASSWORD_FILE = (Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_AUTH_PASSWORD_FILE") $SourceRoot $Root "auth-password.txt")
        DARKWEB_COLLECTOR_OUTPUT_ROOT = $outputPath
        DARKWEB_TOR_EXPERT_DIR = (Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_TOR_EXPERT_DIR") $SourceRoot $Root "tor-expert")
        DARKWEB_TOR_EXECUTABLE = (Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_TOR_EXECUTABLE") $SourceRoot $Root "")
        DARKWEB_TOR_TRANSPORT_EXECUTABLE = (Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_TOR_TRANSPORT_EXECUTABLE") $SourceRoot $Root "")
        DARKWEB_TOR_PT_CONFIG_PATH = (Resolve-RebasedPath (Get-EffectiveEnvironmentValue "DARKWEB_TOR_PT_CONFIG_PATH") $SourceRoot $Root "tor-expert\pt_config.json")
        PLAYWRIGHT_BROWSERS_PATH = (Resolve-RebasedPath (Get-EffectiveEnvironmentValue "PLAYWRIGHT_BROWSERS_PATH") $SourceRoot $Root "playwright")
    }
    foreach ($item in $values.GetEnumerator()) {
        $value = if ($item.Value) { [string]$item.Value } else { $null }
        [Environment]::SetEnvironmentVariable($item.Key, $value, $EnvironmentTarget)
        if ($null -eq $value) { Remove-Item -Path "Env:$($item.Key)" -ErrorAction SilentlyContinue }
        else { Set-Item -Path "Env:$($item.Key)" -Value $value }
    }
}

function Show-Status([string]$CurrentRoot) {
    $applicationRoot = Get-EffectiveEnvironmentValue "DARKWEB_APP_ROOT"
    if (-not $applicationRoot) { $applicationRoot = Join-Path $CurrentRoot "app" }
    Write-Host "Darkweb data storage"
    Write-Host "  Control config: $ConfigPath"
    Write-Host "  Data root:      $CurrentRoot"
    Write-Host "  Application:    $applicationRoot"
    if ($installation -and $installation.current_root) {
        Write-Host "  Active app:      $([string]$installation.current_root)"
    }
    Write-Host "  Migration root: $(Join-Path $CurrentRoot 'migrations')"
    Write-Host "  Garnet data:    $(Join-Path $CurrentRoot 'garnet-data')"
    Write-Host "  SQLite fallback:$(Join-Path $CurrentRoot 'collector.db')"
    Write-Host "  Free space:     $([Math]::Round((Get-FreeBytes $CurrentRoot) / 1GB, 2)) GiB"
    foreach ($entry in @(
        @{ Label = "Current database"; Name = "DARKWEB_COLLECTOR_DB_PATH" },
        @{ Label = "Current output"; Name = "DARKWEB_COLLECTOR_OUTPUT_ROOT" },
        @{ Label = "Garnet data"; Name = "DARKWEB_GARNET_DATA_ROOT" },
        @{ Label = "Active release"; Name = "DARKWEB_ACTIVE_RELEASE_FILE" }
    )) {
        $value = Get-EffectiveEnvironmentValue $entry.Name
        if (-not $value) { continue }
        Write-Host ("  {0}: {1}" -f $entry.Label, $value)
        if (-not (Test-PathUnder $value $CurrentRoot) -and [IO.Path]::GetFullPath($value).TrimEnd("\") -ine $CurrentRoot.TrimEnd("\")) {
            Write-Warn "$($entry.Label) is outside the selected data root and will be preserved unless it is under the old data root."
        }
    }
    $services = @(Get-CimInstance Win32_Service -Filter "Name LIKE 'postgresql%'" -ErrorAction SilentlyContinue)
    $service = $services | Where-Object { $_.Name -match '-16$' -or [string]$_.PathName -match '(?i)\\16\\' } | Select-Object -First 1
    if (-not $service) { $service = $services | Select-Object -First 1 }
    if ($service -and [string]$service.PathName -match '(?i)(?:^|\s)-D\s+(?:"([^"]+)"|([^\s]+))') {
        $postgresqlPath = if ($matches[1]) { $matches[1] } else { $matches[2] }
        Write-Host "  PostgreSQL data:$postgresqlPath"
        if (-not (Test-PathUnder $postgresqlPath $CurrentRoot) -and [IO.Path]::GetFullPath($postgresqlPath).TrimEnd("\") -ine $CurrentRoot.TrimEnd("\")) {
            Write-Warn "Existing PostgreSQL data is outside the selected data root; it is not moved automatically."
        }
    }
}

function Enter-MaintenanceLock {
    $stateRoot = [string][Environment]::GetEnvironmentVariable("DARKWEB_UPDATE_STATE_DIR", "User")
    if (-not $stateRoot) { $stateRoot = [string]$env:DARKWEB_UPDATE_STATE_DIR }
    if (-not $stateRoot) { $stateRoot = $ControlRoot }
    $stateRoot = [System.IO.Path]::GetFullPath($stateRoot)
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    $path = Join-Path $stateRoot "update.lock"
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while ([DateTime]::UtcNow -lt $deadline) {
        $stream = $null
        try {
            $stream = [System.IO.File]::Open($path, "OpenOrCreate", "ReadWrite", "ReadWrite")
            if ($stream.Length -eq 0) {
                $stream.WriteByte(48)
                $stream.Flush()
            }
            $stream.Lock(0, 1)
            return $stream
        }
        catch [System.IO.IOException] {
            if ($stream) { $stream.Dispose() }
            Start-Sleep -Milliseconds 250
        }
    }
    throw "Another update, data migration, or maintenance operation is still running."
}

function Restore-TextFile([string]$Path, $Content) {
    if ($null -eq $Content) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        return
    }
    $temporary = "$Path.restore-$PID"
    $Content | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

$exitCode = 0
$maintenanceLock = $null
try {
    $firstRunSetup = $Action -eq "first-run"
    if ($firstRunSetup -and -not $DataRoot -and (Test-DataRootConfigured)) {
        exit 0
    }
    if ($firstRunSetup -and -not $DataRoot) {
        $DataRoot = Select-FirstRunDataRoot
    }
    $currentRoot = Read-ConfiguredDataRoot
    if ($Action -eq "status") {
        Show-Status $currentRoot
        exit 0
    }
    $maintenanceLock = Enter-MaintenanceLock
    if ($Action -eq "cleanup") {
        $previousRoot = Read-PreviousDataRoot
        if (-not $previousRoot) { throw "No previous data root is recorded for cleanup" }
        if ($previousRoot -ieq $currentRoot) { throw "Previous and current data roots are the same" }
        Remove-VerifiedPreviousData $previousRoot $currentRoot
        Write-DataRootConfig $currentRoot $previousRoot $true
        Remove-Item -LiteralPath $CopyManifestPath -Force
        Show-Status $currentRoot
        exit 0
    }
    $targetRoot = Resolve-SafeDataRoot $DataRoot
    if ($firstRunSetup) {
        $managedFileCount = @(Get-ManagedFiles $currentRoot).Count
        $Action = if ($currentRoot -ine $targetRoot -and $managedFileCount -gt 0) { "migrate" } else { "apply" }
        Write-Info "First-time setup selected $targetRoot ($Action)."
    }
    if ($Action -in @("apply", "migrate") -and (Test-Path -LiteralPath $CopyManifestPath -PathType Leaf)) {
        throw "A previous data-root migration is awaiting verification and cleanup. Run status/cleanup before starting another migration"
    }

    if ($currentRoot -ine $targetRoot -and
        ((Test-PathUnder $targetRoot $currentRoot) -or (Test-PathUnder $currentRoot $targetRoot))) {
        throw "Current and target data roots cannot contain one another"
    }
    $copyBytes = if ($Action -in @("plan", "migrate")) { Get-ManagedBytes $currentRoot } else { 0 }
    Assert-Capacity $targetRoot $copyBytes
    Write-Info "Current data root: $currentRoot"
    Write-Info "Target data root:  $targetRoot"
    if ($Action -eq "plan") {
        Write-Info "Files to copy: $(@(Get-ManagedFiles $currentRoot).Count)"
        Write-Info "Bytes to copy: $copyBytes"
        if ($currentRoot -ine $targetRoot -and (Test-Path -LiteralPath $targetRoot -PathType Container) -and
            @(Get-ChildItem -LiteralPath $targetRoot -Force).Count -gt 0) {
            Write-Warn "Target directory is not empty; apply/migrate will require -Force after you verify its contents"
        }
        if (Test-Path -LiteralPath $CopyManifestPath -PathType Leaf) {
            Write-Warn "A previous migration is still awaiting verification and cleanup"
        }
        Write-Info "No files or configuration were changed."
        exit 0
    }

    if ($currentRoot -ine $targetRoot -and (Test-Path -LiteralPath $targetRoot -PathType Container) -and
        @(Get-ChildItem -LiteralPath $targetRoot -Force).Count -gt 0 -and -not $Force) {
        throw "Target directory is not empty. Choose an empty dedicated directory or re-run with -Force after verifying it"
    }

    if ($Action -eq "apply" -and $currentRoot -ine $targetRoot -and @(Get-ManagedFiles $currentRoot).Count -gt 0) {
        throw "Existing data was found at $currentRoot. Use the migrate action instead of apply."
    }

    $wasRunning = Test-ProjectRunning
    $oldEnvironment = @{}
    foreach ($name in $ManagedEnvironment) {
        $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, $EnvironmentTarget)
    }
    $oldConfig = if (Test-Path -LiteralPath $ConfigPath) { Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 } else { $null }
    $oldCopyManifest = if (Test-Path -LiteralPath $CopyManifestPath) { Get-Content -LiteralPath $CopyManifestPath -Raw -Encoding UTF8 } else { $null }
    $installationPath = $InstallationStatePath
    $oldInstallation = if (Test-Path -LiteralPath $installationPath) { Get-Content -LiteralPath $installationPath -Raw -Encoding UTF8 } else { $null }
    $servicesStopped = $false
    try {
        if ($currentRoot -ine $targetRoot -and $wasRunning) {
            $servicesStopped = $true
            & $Launcher stop
            if ($LASTEXITCODE -ne 0) { throw "Failed to stop project services" }
        }
        if ($Action -eq "migrate" -and $currentRoot -ine $targetRoot) {
            Copy-AndVerifyData $currentRoot $targetRoot
            Update-MigrationMetadata $currentRoot $targetRoot
            Write-CopyManifest $currentRoot $targetRoot
        }
        New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
        Write-DataRootConfig $targetRoot $(if ($Action -eq "migrate" -and $currentRoot -ine $targetRoot) { $currentRoot } else { "" })
        Set-ManagedEnvironment $targetRoot $currentRoot
        if ($wasRunning -and -not $NoRestart) {
            & $Launcher start
            if ($LASTEXITCODE -ne 0 -or -not (Test-ProjectRunning)) { throw "Project did not become healthy on the new data root" }
        }
    }
    catch {
        $failure = $_
        if ($wasRunning -and $servicesStopped) {
            & $Launcher stop | Out-Null
        }
        Restore-TextFile $ConfigPath $oldConfig
        Restore-TextFile $CopyManifestPath $oldCopyManifest
        Restore-TextFile $installationPath $oldInstallation
        foreach ($name in $ManagedEnvironment) {
            [Environment]::SetEnvironmentVariable($name, $oldEnvironment[$name], $EnvironmentTarget)
            if ($null -eq $oldEnvironment[$name]) { Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue }
            else { Set-Item -Path "Env:$name" -Value $oldEnvironment[$name] }
        }
        if ($wasRunning) {
            & $Launcher start | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Warn "Failed to restart the previous project environment during rollback" }
        }
        throw $failure
    }

    Write-Info "Data root configured successfully: $targetRoot"
    if ($Action -eq "migrate" -and $currentRoot -ine $targetRoot) {
        if ($firstRunSetup) {
            Write-Info "The source data was preserved at $currentRoot for rollback. Keep it until the new installation has been verified."
        }
        else {
            Write-Info "The source data was preserved at $currentRoot for rollback. After verification, run configure-data-root.cmd cleanup; do not delete the whole control directory manually."
        }
    }
    Show-Status $targetRoot
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
}
finally {
    if ($maintenanceLock) {
        try { $maintenanceLock.Unlock(0, 1) } catch {}
        $maintenanceLock.Dispose()
    }
}
exit $exitCode
