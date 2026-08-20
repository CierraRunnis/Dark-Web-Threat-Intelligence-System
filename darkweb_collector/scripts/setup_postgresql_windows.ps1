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
$UserDataRoot = Join-Path $env:LOCALAPPDATA "DarkWebThreatIntel"
$TargetConfigPath = Join-Path $UserDataRoot "postgresql-target.json"
$SetupResultPath = Join-Path $UserDataRoot "postgresql-setup-result.json"
$ActiveReleasePath = Join-Path $UserDataRoot "active-release.json"
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
    New-Item -ItemType Directory -Path $UserDataRoot -Force | Out-Null
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
        [string]$PostgreSqlBin
    )
    New-Item -ItemType Directory -Path $UserDataRoot -Force | Out-Null
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
    Write-Host "Windows PostgreSQL one-click setup plan"
    Write-Host "  Package:  $PackageId (installed through winget when missing)"
    Write-Host "  Endpoint: 127.0.0.1:$Port"
    Write-Host "  Database: $DatabaseName"
    Write-Host "  Role:     $ApplicationUser"
    Write-Host "  Project:  $ProjectRootPath"
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
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (-not $winget) {
            throw "winget is unavailable; install Microsoft App Installer first"
        }
        $bootstrapPassword = New-RandomPassword
        Add-SensitiveValue $bootstrapPassword
        $override = "--mode unattended --unattendedmodeui none --superpassword $bootstrapPassword --servicepassword $bootstrapPassword --serverport $Port --enable-components server,commandlinetools --disable-components pgAdmin,stackbuilder"
        if (-not $PSCmdlet.ShouldProcess($PackageId, "Install PostgreSQL with winget")) {
            return 0
        }
        Write-Info "Installing $PackageId through winget"
        & $winget.Source install --id $PackageId --exact --silent --scope machine --accept-package-agreements --accept-source-agreements --override $override
        $wingetExitCode = $LASTEXITCODE
        $tools = Find-PostgreSqlTools
        if ($wingetExitCode -ne 0 -and -not $tools) {
            throw "winget PostgreSQL installation failed with exit code $wingetExitCode"
        }
        if ($wingetExitCode -ne 0) {
            Write-Warn "winget returned exit code $wingetExitCode, but PostgreSQL tools are installed; continuing with service and database verification"
        }
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

    Save-TargetConfig $applicationPassword $superuserPassword $tools.Bin
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
