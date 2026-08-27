[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "status", "plan")]
    [string]$Action = "install",

    [ValidateRange(1024, 65535)]
    [int]$Port = 5432,

    [ValidatePattern("^[a-z][a-z0-9_]{0,62}$")]
    [string]$DatabaseName = "darkweb_intelligence",

    [ValidatePattern("^[a-z][a-z0-9_]{0,62}$")]
    [string]$ApplicationUser = "darkweb_app",

    [ValidateSet("16")]
    [string]$PostgreSqlMajor = "16",

    [string]$ProjectRoot = "",
    [string]$DataRoot = "",

    [switch]$ResetApplicationPassword,
    [switch]$NoRestart,
    [switch]$OneClick,
    [switch]$Pause
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRootPath = if ($ProjectRoot) {
    [IO.Path]::GetFullPath($ProjectRoot)
}
else {
    [IO.Path]::GetFullPath((Join-Path $ScriptDir "..\.."))
}
$CollectorRoot = Join-Path $ProjectRootPath "darkweb_collector"
$Launcher = Join-Path $CollectorRoot "scripts\start_all_services_windows.ps1"
$PackageId = "PostgreSQL.PostgreSQL.$PostgreSqlMajor"
$PostgreSqlInstallerVersion = "16.15-1"
$PostgreSqlInstallerUrl = "https://get.enterprisedb.com/postgresql/postgresql-16.15-1-windows-x64.exe"
$PostgreSqlInstallerSha256 = "de926fefad00e313e212cd438c0f04bf033e200099ad56c012724efcebed79f2"
$LocalAppDataRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } elseif ($env:USERPROFILE) { Join-Path $env:USERPROFILE "AppData\Local" } else { Join-Path $ProjectRootPath ".runtime\user" }
$ControlRoot = [IO.Path]::GetFullPath((Join-Path $LocalAppDataRoot "DarkWebThreatIntel"))
$DataRootConfigPath = Join-Path $ControlRoot "data-root.json"
$configuredDataRoot = if ($DataRoot) {
    $DataRoot
}
elseif ($env:DARKWEB_DATA_ROOT) {
    $env:DARKWEB_DATA_ROOT
}
elseif ([Environment]::GetEnvironmentVariable("DARKWEB_DATA_ROOT", "User")) {
    [Environment]::GetEnvironmentVariable("DARKWEB_DATA_ROOT", "User")
}
elseif ($env:DARKWEB_USER_DATA_ROOT) {
    $env:DARKWEB_USER_DATA_ROOT
}
elseif (Test-Path -LiteralPath $DataRootConfigPath -PathType Leaf) {
    try {
        $dataRootConfig = Get-Content -LiteralPath $DataRootConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([int]$dataRootConfig.format -ne 1 -or -not $dataRootConfig.data_root) {
            throw "unsupported configuration"
        }
        [string]$dataRootConfig.data_root
    }
    catch {
        throw "Data root configuration is invalid: $DataRootConfigPath"
    }
}
else {
    $ControlRoot
}
if (-not [IO.Path]::IsPathRooted($configuredDataRoot)) {
    throw "DataRoot must be an absolute path below a drive root"
}
$DataRootPath = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($configuredDataRoot)).TrimEnd("\")
if ($DataRootPath.StartsWith("\\", [StringComparison]::Ordinal)) {
    throw "DataRoot must be on a local Windows volume; network and WSL UNC paths are not supported"
}
if ($DataRootPath -ieq [IO.Path]::GetPathRoot($DataRootPath).TrimEnd("\")) {
    throw "DataRoot cannot be a drive root; use a dedicated directory such as D:\DarkWebThreatIntel"
}
foreach ($protectedDataRoot in @($env:SystemRoot, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    if (-not $protectedDataRoot) { continue }
    $protectedPath = [IO.Path]::GetFullPath($protectedDataRoot).TrimEnd("\")
    if ($DataRootPath -ieq $protectedPath -or
        $DataRootPath.StartsWith($protectedPath + "\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "DataRoot cannot be under a protected system directory: $protectedPath"
    }
}
$PostgreSqlDataDirectory = Join-Path $DataRootPath "postgresql\$PostgreSqlMajor\data"
$TargetConfigPath = Join-Path $ControlRoot "postgresql-target.json"
$SetupResultPath = Join-Path $ControlRoot "postgresql-setup-result.json"
$ActiveReleasePath = if ($env:DARKWEB_ACTIVE_RELEASE_FILE) { [IO.Path]::GetFullPath($env:DARKWEB_ACTIVE_RELEASE_FILE) } else { Join-Path $DataRootPath "active-release.json" }
$RuntimePortsPath = Join-Path $CollectorRoot ".runtime\windows\ports.json"
$script:SensitiveValues = [System.Collections.Generic.List[string]]::new()
$script:SkipPause = $false

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message"
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Get-DataRootDriveInfo {
    $candidate = $DataRootPath
    while (-not (Test-Path -LiteralPath $candidate) -and $candidate -ne [IO.Path]::GetPathRoot($candidate)) {
        $candidate = Split-Path -Parent $candidate
    }
    return [IO.DriveInfo]::new([IO.Path]::GetPathRoot($candidate))
}

function Assert-DataRootCapacity {
    New-Item -ItemType Directory -Path $DataRootPath -Force | Out-Null
    $drive = Get-DataRootDriveInfo
    if ($drive.AvailableFreeSpace -lt 2GB) {
        throw "Data root $DataRootPath has less than 2 GiB free"
    }
    if ($drive.AvailableFreeSpace -lt 20GB) {
        Write-Warn "Data root has only $([Math]::Round($drive.AvailableFreeSpace / 1GB, 2)) GiB free: $DataRootPath"
    }
}

function Add-SensitiveValue {
    param([string]$Value)
    if ($Value -and -not $script:SensitiveValues.Contains($Value)) {
        $script:SensitiveValues.Add($Value)
    }
}

function Hide-SensitiveValues {
    param([string]$Message)
    $safe = $Message
    foreach ($value in $script:SensitiveValues) {
        if ($value) {
            $safe = $safe.Replace($value, "***")
        }
    }
    return $safe
}

function Write-SetupResult {
    param(
        [ValidateSet("ok", "error")]
        [string]$Status,
        [string]$Message
    )
    New-Item -ItemType Directory -Path $ControlRoot -Force | Out-Null
    $payload = [ordered]@{
        status = $Status
        message = Hide-SensitiveValues $Message
        updated_at = [DateTimeOffset]::UtcNow.ToString("o")
    }
    $temporaryPath = "$SetupResultPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    try {
        $payload | ConvertTo-Json | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
        Move-Item -LiteralPath $temporaryPath -Destination $SetupResultPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function New-RandomPassword {
    param([int]$Length = 32)
    $alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789-_"
    $bytes = New-Object byte[] ($Length - 4)
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    $tail = -join ($bytes | ForEach-Object { $alphabet[[int]$_ % $alphabet.Length] })
    return "Aa1-$tail"
}

function ConvertTo-PlainText {
    param([Security.SecureString]$SecureValue)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Protect-Text {
    param([string]$Value)
    return ConvertTo-SecureString -String $Value -AsPlainText -Force | ConvertFrom-SecureString
}

function Unprotect-Text {
    param([string]$Value)
    return ConvertTo-PlainText (ConvertTo-SecureString -String $Value)
}

function Get-ConfigValue {
    param($Config, [string]$Name)
    if ($null -eq $Config) {
        return $null
    }
    $property = $Config.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Read-TargetConfig {
    if (-not (Test-Path -LiteralPath $TargetConfigPath -PathType Leaf)) {
        return $null
    }
    try {
        $config = Get-Content -LiteralPath $TargetConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([int](Get-ConfigValue $config "format") -ne 1) {
            throw "unsupported format"
        }
        return $config
    }
    catch {
        throw "PostgreSQL target configuration is invalid: $TargetConfigPath"
    }
}

function Test-ActivePostgreSqlRelease {
    if (-not (Test-Path -LiteralPath $ActiveReleasePath -PathType Leaf)) {
        return $false
    }
    try {
        $release = Get-Content -LiteralPath $ActiveReleasePath -Raw -Encoding UTF8 | ConvertFrom-Json
        return ([int](Get-ConfigValue $release "format") -eq 1) -and
            ([string](Get-ConfigValue $release "database_engine") -eq "postgresql")
    }
    catch {
        throw "Active release configuration is invalid: $ActiveReleasePath"
    }
}

function Set-PrivateFileAcl {
    param([string]$Path)
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $acl = [Security.AccessControl.FileSecurity]::new()
        $acl.SetOwner($identity.User)
        $acl.SetAccessRuleProtection($true, $false)
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $identity.User,
            [Security.AccessControl.FileSystemRights]::FullControl,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
        [IO.File]::SetAccessControl($Path, $acl)
    }
    catch {
        throw "Unable to protect PostgreSQL target configuration ACL: $Path"
    }
}

function Save-TargetConfig {
    param(
        [string]$ApplicationPassword,
        [string]$SuperuserPassword,
        [string]$PostgreSqlBin,
        [string]$DataDirectory
    )
    New-Item -ItemType Directory -Path $ControlRoot -Force | Out-Null
    $payload = [ordered]@{
        format = 1
        host = "127.0.0.1"
        port = $Port
        database = $DatabaseName
        application_user = $ApplicationUser
        application_password_dpapi = Protect-Text $ApplicationPassword
        postgres_superuser = "postgres"
        postgres_password_dpapi = Protect-Text $SuperuserPassword
        postgresql_bin = $PostgreSqlBin
        data_directory = $DataDirectory
        package_id = $PackageId
        configured_at = [DateTimeOffset]::UtcNow.ToString("o")
    }
    $temporaryPath = "$TargetConfigPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    try {
        $payload | ConvertTo-Json | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
        Set-PrivateFileAcl $temporaryPath
        Move-Item -LiteralPath $temporaryPath -Destination $TargetConfigPath -Force
        Set-PrivateFileAcl $TargetConfigPath
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Add-UserPathEntry {
    param([string]$Path)
    $entries = @([Environment]::GetEnvironmentVariable("Path", "User") -split ";" | Where-Object { $_ })
    if (-not ($entries | Where-Object { $_.TrimEnd("\") -ieq $Path.TrimEnd("\") })) {
        [Environment]::SetEnvironmentVariable("Path", (($entries + $Path) -join ";"), "User")
    }
    if (-not ($env:Path -split ";" | Where-Object { $_.TrimEnd("\") -ieq $Path.TrimEnd("\") })) {
        $env:Path = "$Path;$env:Path"
    }
}

function Install-VerifiedPostgreSql {
    param([string]$BootstrapPassword)

    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "PostgreSQL $PostgreSqlInstallerVersion requires a 64-bit Windows operating system"
    }
    if ($env:DARKWEB_POSTGRESQL_AUTO_INSTALL -eq "0") {
        throw "PostgreSQL is missing and DARKWEB_POSTGRESQL_AUTO_INSTALL=0"
    }
    if (-not $PSCmdlet.ShouldProcess("EDB PostgreSQL $PostgreSqlInstallerVersion", "Install verified PostgreSQL distribution")) {
        return $false
    }

    Assert-DataRootCapacity
    $stagingRoot = Join-Path $DataRootPath (".postgresql-setup-" + [Guid]::NewGuid().ToString("N"))
    $installerPath = Join-Path $stagingRoot "postgresql-installer.exe"
    $sourceInstallerPath = [string]$env:DARKWEB_POSTGRESQL_INSTALLER_PATH
    $previousProgressPreference = $ProgressPreference
    try {
        New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null
        $ProgressPreference = "SilentlyContinue"
        if ($sourceInstallerPath) {
            $sourceInstallerPath = [IO.Path]::GetFullPath($sourceInstallerPath)
            if (-not (Test-Path -LiteralPath $sourceInstallerPath -PathType Leaf)) {
                throw "PostgreSQL installer was not found: $sourceInstallerPath"
            }
            Copy-Item -LiteralPath $sourceInstallerPath -Destination $installerPath
        }
        else {
            Write-Info "Downloading EDB PostgreSQL $PostgreSqlInstallerVersion"
            [Net.ServicePointManager]::SecurityProtocol =
                [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -Uri $PostgreSqlInstallerUrl -OutFile $installerPath -TimeoutSec 600
        }

        $actualHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $PostgreSqlInstallerSha256) {
            throw "PostgreSQL installer checksum verification failed"
        }

        Write-Info "Installing verified EDB PostgreSQL $PostgreSqlInstallerVersion"
        $arguments = @(
            "--mode", "unattended",
            "--unattendedmodeui", "none",
            "--superpassword", $BootstrapPassword,
            "--servicepassword", $BootstrapPassword,
            "--serverport", [string]$Port,
            "--datadir", ('"' + $PostgreSqlDataDirectory + '"'),
            "--enable-components", "server,commandlinetools",
            "--disable-components", "pgAdmin,stackbuilder"
        )
        $process = Start-Process -FilePath $installerPath -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
        if ($process.ExitCode -ne 0) {
            throw "EDB PostgreSQL installation failed with exit code $($process.ExitCode)"
        }
        return $true
    }
    finally {
        $ProgressPreference = $previousProgressPreference
        if (Test-Path -LiteralPath $stagingRoot) {
            Remove-Item -LiteralPath $stagingRoot -Recurse -Force
        }
    }
}

function Find-PostgreSqlTools {
    $candidates = [System.Collections.Generic.List[string]]::new()
    $command = Get-Command psql.exe -ErrorAction SilentlyContinue
    if ($command) {
        $candidates.Add($command.Source)
    }
    foreach ($root in @(
        (Join-Path $env:ProgramFiles "PostgreSQL"),
        (Join-Path ${env:ProgramFiles(x86)} "PostgreSQL")
    )) {
        if (-not $root -or -not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }
        foreach ($directory in Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue) {
            $candidate = Join-Path $directory.FullName "bin\psql.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $candidates.Add($candidate)
            }
        }
    }
    $selected = $candidates | Sort-Object -Unique -Descending | Select-Object -First 1
    if (-not $selected) {
        return $null
    }
    $bin = Split-Path -Parent $selected
    $ready = Join-Path $bin "pg_isready.exe"
    if (-not (Test-Path -LiteralPath $ready -PathType Leaf)) {
        return $null
    }
    return [pscustomobject]@{ Psql = $selected; PgIsReady = $ready; Bin = $bin }
}

function Get-PostgreSqlDataDirectory {
    try {
        $services = @(Get-CimInstance Win32_Service -Filter "Name LIKE 'postgresql%'" -ErrorAction Stop)
        $service = $services | Where-Object {
            $_.Name -match "-$([Regex]::Escape($PostgreSqlMajor))$" -or
            [string]$_.PathName -match "(?i)\\$([Regex]::Escape($PostgreSqlMajor))\\"
        } | Select-Object -First 1
        if (-not $service) { $service = $services | Select-Object -First 1 }
        if ($service -and [string]$service.PathName -match '(?i)(?:^|\s)-D\s+(?:"([^"]+)"|([^\s]+))') {
            $servicePath = if ($matches[1]) { $matches[1] } else { $matches[2] }
            if ($servicePath) {
                return [IO.Path]::GetFullPath($servicePath)
            }
        }
    }
    catch {
    }
    $config = Read-TargetConfig
    $configuredPath = [string](Get-ConfigValue $config "data_directory")
    if ($configuredPath) {
        return [IO.Path]::GetFullPath($configuredPath)
    }
    return ""
}

function Wait-PostgreSql {
    param($Tools, [int]$TimeoutSeconds = 120)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        & $Tools.PgIsReady -h 127.0.0.1 -p $Port -q
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "PostgreSQL did not become ready on 127.0.0.1:$Port"
}

function Start-PostgreSqlServiceIfNeeded {
    param($Tools)
    & $Tools.PgIsReady -h 127.0.0.1 -p $Port -q
    if ($LASTEXITCODE -eq 0) {
        return 0
    }
    $installedMajor = Split-Path (Split-Path $Tools.Bin -Parent) -Leaf
    $services = @(Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue)
    $service = $services | Where-Object { $_.Name -match "-$([Regex]::Escape($installedMajor))$" } | Select-Object -First 1
    if (-not $service) {
        $service = $services | Select-Object -First 1
    }
    if (-not $service -or $service.Status -eq "Running") {
        return 0
    }
    if (-not (Test-Administrator)) {
        if ($OneClick) {
            return Invoke-ElevatedSetup
        }
        throw "Administrator privileges are required to start PostgreSQL service $($service.Name)"
    }
    if ($PSCmdlet.ShouldProcess($service.Name, "Start PostgreSQL service")) {
        Start-Service -Name $service.Name
        Write-Info "Started PostgreSQL service $($service.Name)"
    }
    return 0
}

function Invoke-Psql {
    param(
        $Tools,
        [string]$User,
        [string]$Password,
        [string]$Database,
        [string]$Sql
    )
    $previousPassword = $env:PGPASSWORD
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $env:PGPASSWORD = $Password
        $ErrorActionPreference = "Continue"
        $output = $Sql | & $Tools.Psql --no-password --set ON_ERROR_STOP=on --host 127.0.0.1 --port $Port --username $User --dbname $Database --tuples-only --no-align 2>&1
        $psqlExitCode = $LASTEXITCODE
        if ($psqlExitCode -ne 0) {
            $message = Hide-SensitiveValues (($output | Out-String).Trim())
            throw "psql failed: $message"
        }
        return @($output)
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($null -eq $previousPassword) {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
        else {
            $env:PGPASSWORD = $previousPassword
        }
    }
}

function Test-ProjectRunning {
    if (-not (Test-Path -LiteralPath $RuntimePortsPath -PathType Leaf)) {
        return $false
    }
    try {
        $ports = Get-Content -LiteralPath $RuntimePortsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $apiPort = [int](Get-ConfigValue $ports "api_port")
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$apiPort/api/health" -TimeoutSec 3
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Restart-ProjectIfRunning {
    if ($NoRestart -or -not (Test-Path -LiteralPath $Launcher -PathType Leaf) -or -not (Test-ProjectRunning)) {
        return
    }
    Write-Info "Restarting the running project so the migration target becomes available"
    & $Launcher stop
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stop the project services"
    }
    & $Launcher start
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to restart the project services"
    }
}

function Show-Plan {
    $drive = Get-DataRootDriveInfo
    Write-Host "Windows PostgreSQL one-click setup plan"
    Write-Host "  Package:  EDB PostgreSQL $PostgreSqlInstallerVersion (verified direct download when missing)"
    Write-Host "  Endpoint: 127.0.0.1:$Port"
    Write-Host "  Database: $DatabaseName"
    Write-Host "  Role:     $ApplicationUser"
    Write-Host "  Project:  $ProjectRootPath"
    Write-Host "  Data root:$DataRootPath"
    Write-Host "  New data: $PostgreSqlDataDirectory"
    Write-Host "  Free:     $([Math]::Round($drive.AvailableFreeSpace / 1GB, 2)) GiB"
    Write-Host "  Config:   $TargetConfigPath"
    Write-Host "  Changes:  install service, create database/role, grant schema-create permission, configure migration target"
    Write-Host "  Tables:   created in an isolated dwti_<bundle_id> schema when a .dwti package is imported"
    Write-Host "  Safety:   current SQLite data is not imported, deleted, or switched by this setup tool"
}

function Show-Status {
    $tools = Find-PostgreSqlTools
    if (-not $tools) {
        Write-Warn "PostgreSQL command-line tools were not found"
        return 1
    }
    $version = (& $tools.Psql --version 2>$null | Out-String).Trim()
    Write-Info $version
    $actualDataDirectory = Get-PostgreSqlDataDirectory
    if ($actualDataDirectory) {
        Write-Info "PostgreSQL data directory: $actualDataDirectory"
        $dataRootPrefix = $DataRootPath.TrimEnd("\") + "\"
        if (-not $actualDataDirectory.StartsWith($dataRootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Warn "Existing PostgreSQL data is outside the selected data root; this setup tool will reuse it without moving it"
        }
    }
    & $tools.PgIsReady -h 127.0.0.1 -p $Port -q
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "PostgreSQL is not accepting connections on 127.0.0.1:$Port"
        return 1
    }
    $config = Read-TargetConfig
    if (-not $config) {
        Write-Warn "PostgreSQL is running, but the project target has not been configured"
        return 1
    }
    try {
        $password = Unprotect-Text ([string](Get-ConfigValue $config "application_password_dpapi"))
        Add-SensitiveValue $password
        $tableCount = Invoke-Psql $tools $ApplicationUser $password $DatabaseName "SELECT count(*) FROM information_schema.tables WHERE table_schema LIKE 'dwti_%';"
        Write-Info "Migration target is ready: 127.0.0.1:$Port/$DatabaseName (imported release tables: $($tableCount[-1]))"
        return 0
    }
    catch {
        Write-Warn (Hide-SensitiveValues $_.Exception.Message)
        return 1
    }
}

function Request-SuperuserPassword {
    $secure = Read-Host "Enter the existing PostgreSQL postgres password" -AsSecureString
    $plain = ConvertTo-PlainText $secure
    if (-not $plain) {
        throw "PostgreSQL superuser password cannot be empty"
    }
    return $plain
}

function Invoke-ElevatedSetup {
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $PSCommandPath + '"'),
        "install",
        "-Port", [string]$Port,
        "-DatabaseName", $DatabaseName,
        "-ApplicationUser", $ApplicationUser,
        "-PostgreSqlMajor", $PostgreSqlMajor,
        "-ProjectRoot", ('"' + $ProjectRootPath + '"'),
        "-DataRoot", ('"' + $DataRootPath + '"'),
        "-OneClick"
    )
    if ($ResetApplicationPassword) { $arguments += "-ResetApplicationPassword" }
    if ($NoRestart) { $arguments += "-NoRestart" }
    if ($Pause) { $arguments += "-Pause" }
    $script:SkipPause = $true
    $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
    return $process.ExitCode
}

function Install-PostgreSqlTarget {
    $tools = Find-PostgreSqlTools
    $installedNow = $false
    $bootstrapPassword = ""
    if (-not $tools) {
        if (-not (Test-Administrator)) {
            if ($OneClick) {
                return Invoke-ElevatedSetup
            }
            throw "Administrator privileges are required to install PostgreSQL"
        }
        $bootstrapPassword = New-RandomPassword
        Add-SensitiveValue $bootstrapPassword
        $installed = Install-VerifiedPostgreSql $bootstrapPassword
        if (-not $installed) {
            return 0
        }
        $tools = Find-PostgreSqlTools
        if (-not $tools) {
            throw "PostgreSQL was installed, but psql.exe could not be located"
        }
        $installedNow = $true
    }

    Add-UserPathEntry $tools.Bin
    $serviceExitCode = Start-PostgreSqlServiceIfNeeded $tools
    if ($script:SkipPause) {
        return $serviceExitCode
    }
    Wait-PostgreSql $tools
    $actualDataDirectory = Get-PostgreSqlDataDirectory
    if (-not $actualDataDirectory -and $installedNow) {
        $actualDataDirectory = $PostgreSqlDataDirectory
    }
    if ($actualDataDirectory) {
        $dataRootPrefix = $DataRootPath.TrimEnd("\") + "\"
        if (-not $actualDataDirectory.StartsWith($dataRootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Warn "Reusing existing PostgreSQL data outside the selected data root: $actualDataDirectory"
        }
    }
    $config = Read-TargetConfig
    $matchingConfig = $config -and
        ([string](Get-ConfigValue $config "host") -eq "127.0.0.1") -and
        ([int](Get-ConfigValue $config "port") -eq $Port) -and
        ([string](Get-ConfigValue $config "database") -eq $DatabaseName) -and
        ([string](Get-ConfigValue $config "application_user") -eq $ApplicationUser)

    $applicationPassword = ""
    if ($matchingConfig) {
        $applicationPassword = Unprotect-Text ([string](Get-ConfigValue $config "application_password_dpapi"))
    }
    if (-not $applicationPassword -or $ResetApplicationPassword) {
        $applicationPassword = New-RandomPassword
    }
    Add-SensitiveValue $applicationPassword

    $superuserPassword = $bootstrapPassword
    if (-not $superuserPassword -and $matchingConfig) {
        $protectedSuperuserPassword = [string](Get-ConfigValue $config "postgres_password_dpapi")
        if ($protectedSuperuserPassword) {
            $superuserPassword = Unprotect-Text $protectedSuperuserPassword
        }
    }
    if (-not $superuserPassword) {
        $superuserPassword = Request-SuperuserPassword
    }
    Add-SensitiveValue $superuserPassword

    $roleExists = (Invoke-Psql $tools "postgres" $superuserPassword "postgres" "SELECT 1 FROM pg_roles WHERE rolname = '$ApplicationUser';") -contains "1"
    if ($roleExists -and -not $matchingConfig -and -not $ResetApplicationPassword) {
        throw "Role $ApplicationUser already exists but no matching local configuration is available. Re-run with -ResetApplicationPassword to take ownership of this project role."
    }
    if ($roleExists -and $ResetApplicationPassword -and (Test-ActivePostgreSqlRelease)) {
        throw "Cannot reset the application role password while a PostgreSQL release is active; doing so would break the current active connection."
    }
    if (-not $roleExists) {
        Invoke-Psql $tools "postgres" $superuserPassword "postgres" "CREATE ROLE $ApplicationUser LOGIN PASSWORD '$applicationPassword';" | Out-Null
        Write-Info "Created PostgreSQL role $ApplicationUser"
    }
    elseif ($ResetApplicationPassword) {
        Invoke-Psql $tools "postgres" $superuserPassword "postgres" "ALTER ROLE $ApplicationUser LOGIN PASSWORD '$applicationPassword';" | Out-Null
        Write-Info "Reset PostgreSQL role password for $ApplicationUser"
    }

    $databaseExists = (Invoke-Psql $tools "postgres" $superuserPassword "postgres" "SELECT 1 FROM pg_database WHERE datname = '$DatabaseName';") -contains "1"
    if (-not $databaseExists) {
        Invoke-Psql $tools "postgres" $superuserPassword "postgres" "CREATE DATABASE $DatabaseName OWNER $ApplicationUser ENCODING 'UTF8' TEMPLATE template0;" | Out-Null
        Write-Info "Created PostgreSQL database $DatabaseName"
    }
    Invoke-Psql $tools "postgres" $superuserPassword "postgres" "GRANT CONNECT, CREATE, TEMPORARY ON DATABASE $DatabaseName TO $ApplicationUser;" | Out-Null

    $checkSchema = "dwti_setup_check_$([Guid]::NewGuid().ToString('N'))"
    $checkSql = "CREATE SCHEMA $checkSchema AUTHORIZATION $ApplicationUser; CREATE TABLE $checkSchema.connection_check(id BIGINT PRIMARY KEY); INSERT INTO $checkSchema.connection_check VALUES (1); DROP SCHEMA $checkSchema CASCADE;"
    Invoke-Psql $tools $ApplicationUser $applicationPassword $DatabaseName $checkSql | Out-Null
    Write-Info "Verified schema and table creation permissions"

    if ($installedNow) {
        $finalSuperuserPassword = New-RandomPassword
        Add-SensitiveValue $finalSuperuserPassword
        Invoke-Psql $tools "postgres" $superuserPassword "postgres" "ALTER ROLE postgres PASSWORD '$finalSuperuserPassword';" | Out-Null
        $superuserPassword = $finalSuperuserPassword
        Write-Info "Rotated the temporary installer database password"
    }

    $reportedDataDirectory = @(Invoke-Psql $tools "postgres" $superuserPassword "postgres" "SHOW data_directory;")
    if ($reportedDataDirectory.Count -gt 0 -and [string]$reportedDataDirectory[-1]) {
        $actualDataDirectory = [IO.Path]::GetFullPath(([string]$reportedDataDirectory[-1]).Trim())
    }
    Save-TargetConfig $applicationPassword $superuserPassword $tools.Bin $actualDataDirectory
    $encodedPassword = [Uri]::EscapeDataString($applicationPassword)
    $targetUrl = "postgresql://${ApplicationUser}:${encodedPassword}@127.0.0.1:${Port}/${DatabaseName}"
    [Environment]::SetEnvironmentVariable("DARKWEB_MIGRATION_TARGET_DATABASE_URL", $targetUrl, "User")
    $env:DARKWEB_MIGRATION_TARGET_DATABASE_URL = $targetUrl
    Write-Info "Configured DARKWEB_MIGRATION_TARGET_DATABASE_URL for the current user"
    Restart-ProjectIfRunning
    Write-SetupResult "ok" "PostgreSQL migration target is ready"
    Write-Info "PostgreSQL migration target is ready"
    Write-Info "Importing a .dwti package will create and verify all project tables in its own dwti_<bundle_id> schema"
    Write-Info "Current SQLite data and active database selection were not changed"
    return 0
}

$exitCode = 0
try {
    if ($ApplicationUser -eq "postgres") {
        throw "ApplicationUser cannot be the PostgreSQL superuser"
    }
    if ($DatabaseName -in @("postgres", "template0", "template1")) {
        throw "DatabaseName must be a dedicated project database"
    }
    if ($Action -eq "plan") {
        Show-Plan
    }
    elseif ($Action -eq "status") {
        $exitCode = Show-Status
    }
    else {
        $exitCode = Install-PostgreSqlTarget
    }
}
catch {
    $safeError = Hide-SensitiveValues $_.Exception.Message
    Write-SetupResult "error" $safeError
    Write-Host ("[ERROR] " + $safeError) -ForegroundColor Red
    $exitCode = 1
}
finally {
    if ($Pause -and -not $script:SkipPause) {
        Read-Host "Press Enter to close"
    }
}
exit $exitCode
