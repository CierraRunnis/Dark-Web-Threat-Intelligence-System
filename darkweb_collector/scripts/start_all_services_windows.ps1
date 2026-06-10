[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "status", "install", "register")]
    [string]$Action = "start"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SessionName = "bishe-stack-windows"
$ApiHost = "127.0.0.1"
$ApiPort = if ($env:DARKWEB_API_PORT) { [int]$env:DARKWEB_API_PORT } else { 8000 }
$ApiBaseUrl = "http://${ApiHost}:${ApiPort}"
$ApiHealthUrl = "$ApiBaseUrl/api/health"
$ApiJobsUrl = "$ApiBaseUrl/api/jobs"
$FrontendHost = "127.0.0.1"
$FrontendPort = if ($env:DARKWEB_FRONTEND_PORT) { [int]$env:DARKWEB_FRONTEND_PORT } else { 5173 }
$FrontendUrl = "http://${FrontendHost}:${FrontendPort}"
$ServiceWaitSeconds = 45
$SchedulerIntervalSeconds = if ($env:SCHEDULER_INTERVAL_SECONDS) { [int]$env:SCHEDULER_INTERVAL_SECONDS } else { 60 }
$VulnSyncIntervalSeconds = if ($env:VULN_SYNC_INTERVAL_SECONDS) { [int]$env:VULN_SYNC_INTERVAL_SECONDS } else { 3600 }
$VulnSyncLimit = if ($env:VULN_SYNC_LIMIT) { [int]$env:VULN_SYNC_LIMIT } else { 300 }
$BrowserConcurrency = 2
if ($env:DARKWEB_BROWSER_CONCURRENCY) {
    try {
        $BrowserConcurrency = [Math]::Max([int]$env:DARKWEB_BROWSER_CONCURRENCY, 1)
    }
    catch {
        $BrowserConcurrency = 2
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CollectorRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$ProjectRoot = (Resolve-Path (Join-Path $CollectorRoot "..")).Path
$DashboardRoot = Join-Path $ProjectRoot "threat-intelligence-dashboard"
$LocalAppDataRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } elseif ($env:USERPROFILE) { Join-Path $env:USERPROFILE "AppData\Local" } else { Join-Path $ProjectRoot ".runtime\user" }
$VenvDir = Join-Path $CollectorRoot "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$RuntimeDir = Join-Path $CollectorRoot ".runtime\windows"
$LogDir = Join-Path $RuntimeDir "logs"
$PidFile = Join-Path $RuntimeDir "services.json"
$RuntimePortsFile = Join-Path $RuntimeDir "ports.json"
$CommandBinDir = Join-Path $LocalAppDataRoot "DarkWebThreatIntel\bin"
$DarkwebCommandPath = Join-Path $CommandBinDir "darkweb.cmd"
$DefaultUserDataDir = Join-Path $LocalAppDataRoot "DarkWebThreatIntel"
$LegacyCollectorOutputRoot = Join-Path $DefaultUserDataDir "output"
$ProjectCollectorOutputRoot = Join-Path $CollectorRoot "output"
$NodeExePath = ""
$NodeBinDir = ""
$RequirementsStamp = Join-Path $VenvDir ".requirements.sha256"
$PlaywrightStamp = Join-Path $VenvDir ".playwright.chromium.ready"
$PackageLockStamp = Join-Path $DashboardRoot "node_modules\.package-lock.sha256"
$RedisUrl = if ($env:REDIS_URL) { $env:REDIS_URL } else { "redis://127.0.0.1:6379/0" }
$CollectorDbPath = if ($env:DARKWEB_COLLECTOR_DB_PATH) { $env:DARKWEB_COLLECTOR_DB_PATH } else { Join-Path $DefaultUserDataDir "collector.db" }
$CollectorSitesFile = if ($env:DARKWEB_COLLECTOR_SITES_FILE) { $env:DARKWEB_COLLECTOR_SITES_FILE } else { Join-Path $CollectorRoot "sites.yaml" }
$CollectorOutputRoot = if ($env:DARKWEB_COLLECTOR_OUTPUT_ROOT) {
    $configuredOutputRoot = [System.IO.Path]::GetFullPath($env:DARKWEB_COLLECTOR_OUTPUT_ROOT)
    $resolvedLegacyOutputRoot = [System.IO.Path]::GetFullPath($LegacyCollectorOutputRoot)
    if ($configuredOutputRoot -ieq $resolvedLegacyOutputRoot) {
        $ProjectCollectorOutputRoot
    }
    else {
        $env:DARKWEB_COLLECTOR_OUTPUT_ROOT
    }
}
else {
    $ProjectCollectorOutputRoot
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message"
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message"
}

function Stop-WithError {
    param([string]$Message)
    Write-Error "[ERROR] $Message"
    exit 1
}

function Write-StartupTrace {
    param([string]$Message)
    if ($env:DARKWEB_TRACE_STARTUP -eq "1") {
        Write-Info "[trace] $Message"
    }
}

function Invoke-TimedStep {
    param(
        [string]$Name,
        [scriptblock]$Body
    )
    if ($env:DARKWEB_TRACE_STARTUP -ne "1") {
        & $Body
        return
    }

    $started = Get-Date
    Write-StartupTrace "$Name started"
    try {
        & $Body
    }
    finally {
        $elapsed = ((Get-Date) - $started).TotalSeconds
        Write-StartupTrace ("{0} finished in {1:N2}s" -f $Name, $elapsed)
    }
}

function Resolve-RequiredCommand {
    param(
        [string]$Name,
        [string]$Hint
    )
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        Stop-WithError "Missing required command '$Name'. $Hint"
    }
    return $command.Source
}

function Resolve-OptionalCommand {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return $null
}

function Resolve-OptionalCommandPath {
    param([string[]]$Names)
    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    return $null
}

function Resolve-PowerShellCommand {
    $powerShell = Resolve-OptionalCommandPath @("pwsh.exe", "pwsh", "powershell.exe", "powershell")
    if ($powerShell) {
        return $powerShell
    }
    Stop-WithError "PowerShell is required to start background services."
}

function Quote-PS {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Remove-GeneratedDirectory {
    param(
        [string]$Path,
        [string]$AllowedRoot
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
    $resolvedRoot = (Resolve-Path -LiteralPath $AllowedRoot).Path
    $rootPrefix = $resolvedRoot.TrimEnd("\") + "\"
    if (-not ($resolvedPath.Equals($resolvedRoot, [StringComparison]::OrdinalIgnoreCase) -or $resolvedPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase))) {
        Stop-WithError "Refusing to remove generated directory outside project root: $resolvedPath"
    }
    Remove-Item -LiteralPath $resolvedPath -Recurse -Force
}

function Update-ProcessPathFromRegistry {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = New-Object System.Collections.Generic.List[string]
    $seen = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
    if ($machinePath) {
        foreach ($entry in $machinePath -split ";") {
            $trimmed = $entry.Trim()
            if ($trimmed -and $seen.Add($trimmed.TrimEnd("\"))) {
                $parts.Add($trimmed) | Out-Null
            }
        }
    }
    if ($userPath) {
        foreach ($entry in $userPath -split ";") {
            $trimmed = $entry.Trim()
            if ($trimmed -and $seen.Add($trimmed.TrimEnd("\"))) {
                $parts.Add($trimmed) | Out-Null
            }
        }
    }
    if ($env:Path) {
        foreach ($entry in $env:Path -split ";") {
            $trimmed = $entry.Trim()
            if ($trimmed -and $seen.Add($trimmed.TrimEnd("\"))) {
                $parts.Add($trimmed) | Out-Null
            }
        }
    }
    $env:Path = ($parts -join ";")
}

function Add-UserPathEntry {
    param([string]$Path)
    Ensure-Directory $Path
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $entries = @()
    if ($userPath) {
        $entries = $userPath -split ";" | Where-Object { $_ -and $_.Trim() }
    }
    $alreadyPresent = $false
    foreach ($entry in $entries) {
        if ($entry.TrimEnd("\") -ieq $Path.TrimEnd("\")) {
            $alreadyPresent = $true
            break
        }
    }
    if (-not $alreadyPresent) {
        $entries += $Path
        [Environment]::SetEnvironmentVariable("Path", ($entries -join ";"), "User")
    }
    if (($env:Path -split ";") -notcontains $Path) {
        $env:Path = "$Path;$env:Path"
    }
}

function Add-ProcessPathEntry {
    param([string]$Path)
    if (-not $Path) {
        return
    }
    $entries = @($env:Path -split ";" | Where-Object { $_ -and $_.Trim() })
    foreach ($entry in $entries) {
        if ($entry.TrimEnd("\") -ieq $Path.TrimEnd("\")) {
            return
        }
    }
    $env:Path = "$Path;$env:Path"
}

function Set-UserEnv {
    param(
        [string]$Name,
        [string]$Value
    )
    $currentUserValue = [Environment]::GetEnvironmentVariable($Name, "User")
    if ($currentUserValue -ne $Value) {
        [Environment]::SetEnvironmentVariable($Name, $Value, "User")
    }
    $currentProcessValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ($currentProcessValue -ne $Value) {
        Set-Item -Path "Env:$Name" -Value $Value
    }
}

function Test-CommandWorks {
    param(
        [string]$CommandName,
        [string[]]$Arguments = @("--version")
    )
    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if (-not $command) {
        return $false
    }
    $source = $command.Source
    if (-not $source) {
        $source = $command.Name
    }
    try {
        & $source @Arguments *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Resolve-WorkingCommand {
    param(
        [string[]]$Names,
        [string[]]$Arguments = @("--version")
    )
    Update-ProcessPathFromRegistry
    foreach ($name in $Names) {
        if (Test-CommandWorks -CommandName $name -Arguments $Arguments) {
            $command = Get-Command $name -ErrorAction Stop
            if ($command.Source) {
                return $command.Source
            }
            return $command.Name
        }
    }
    return $null
}

function Install-WingetPackage {
    param(
        [string]$PackageId,
        [string]$DisplayName,
        [string]$Override = ""
    )
    $winget = Resolve-OptionalCommand "winget"
    if (-not $winget) {
        Stop-WithError "Missing '$DisplayName' and winget is unavailable. Install App Installer from Microsoft Store, or install $DisplayName manually and run darkweb again."
    }

    Write-Info "Installing $DisplayName with winget"
    $arguments = @(
        "install",
        "--id",
        $PackageId,
        "--exact",
        "--accept-package-agreements",
        "--accept-source-agreements"
    )
    if ($Override) {
        $arguments += @("--override", $Override)
    }
    & $winget @arguments
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "winget failed to install $DisplayName. Install it manually, reopen the terminal, and run darkweb again."
    }
    Update-ProcessPathFromRegistry
}

function Resolve-DockerCommand {
    return (Resolve-OptionalCommandPath @("docker.exe", "docker"))
}

function Get-FileHashText {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
}

function Get-RedisEndpoint {
    $endpoint = [pscustomobject]@{
        Host = "127.0.0.1"
        Port = 6379
        IsLocal = $true
    }

    try {
        $uri = [Uri]$RedisUrl
        if ($uri.Host) {
            $endpoint.Host = $uri.Host
        }
        if ($uri.Port -gt 0) {
            $endpoint.Port = $uri.Port
        }
    }
    catch {
    }

    $localHosts = @("localhost", "127.0.0.1", "::1", "[::1]")
    $endpoint.IsLocal = $localHosts -contains $endpoint.Host.ToLowerInvariant()
    return $endpoint
}

function Test-RedisReady {
    $endpoint = Get-RedisEndpoint
    $redisCli = Resolve-OptionalCommandPath @("redis-cli.exe", "redis-cli")
    if ($redisCli) {
        try {
            $output = & $redisCli -u $RedisUrl ping 2>$null
            if ($LASTEXITCODE -eq 0 -and $output -match "PONG") {
                return $true
            }
        }
        catch {
        }
    }

    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($endpoint.Host, $endpoint.Port, $null, $null)
        $connected = $async.AsyncWaitHandle.WaitOne(1000, $false)
        if ($connected) {
            $client.EndConnect($async)
        }
        $client.Close()
        return $connected
    }
    catch {
        return $false
    }
}

function Wait-ForRedis {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-RedisReady) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Wait-ForHttp {
    param(
        [string]$Url,
        [int]$TimeoutSeconds
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
            return $true
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Set-ApiPort {
    param([int]$Port)
    $script:ApiPort = $Port
    $script:ApiBaseUrl = "http://${script:ApiHost}:${script:ApiPort}"
    $script:ApiHealthUrl = "$script:ApiBaseUrl/api/health"
    $script:ApiJobsUrl = "$script:ApiBaseUrl/api/jobs"
}

function Set-FrontendPort {
    param([int]$Port)
    $script:FrontendPort = $Port
    $script:FrontendUrl = "http://${script:FrontendHost}:${script:FrontendPort}"
}

function Save-RuntimePorts {
    Ensure-Directory $RuntimeDir
    [pscustomobject]@{
        api_port = $ApiPort
        api_base_url = $ApiBaseUrl
        frontend_port = $FrontendPort
        frontend_url = $FrontendUrl
        updated_at = (Get-Date).ToString("s")
    } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $RuntimePortsFile -Encoding UTF8
}

function Load-RuntimePorts {
    if (-not (Test-Path -LiteralPath $RuntimePortsFile)) {
        return
    }
    try {
        $ports = Get-Content -LiteralPath $RuntimePortsFile -Raw | ConvertFrom-Json
        if ($ports.api_port) {
            Set-ApiPort -Port ([int]$ports.api_port)
        }
        if ($ports.frontend_port) {
            Set-FrontendPort -Port ([int]$ports.frontend_port)
        }
    }
    catch {
        Write-Warn "Could not read runtime ports from ${RuntimePortsFile}: $($_.Exception.Message)"
    }
}

function Test-DarkwebApiReady {
    try {
        $payload = Invoke-RestMethod -Uri $ApiJobsUrl -TimeoutSec 3
        if ($null -eq $payload.site_health) {
            return $false
        }
        return (@($payload.site_health).Count -gt 0)
    }
    catch {
        return $false
    }
}

function Test-DarkwebFrontendReady {
    try {
        $response = Invoke-WebRequest -Uri $FrontendUrl -UseBasicParsing -TimeoutSec 3
        $htmlReady = ($response.Content -match "全球威胁情报监控系统" -or $response.Content -match "/src/main.js")
        if (-not $htmlReady) {
            return $false
        }
        $jobsPayload = Invoke-RestMethod -Uri "$FrontendUrl/api/jobs" -TimeoutSec 3
        return ($null -ne $jobsPayload.site_health -and @($jobsPayload.site_health).Count -gt 0)
    }
    catch {
        return $false
    }
}

function Wait-ForDarkwebApi {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-DarkwebApiReady) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Wait-ForDarkwebFrontend {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-DarkwebFrontendReady) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Get-ListeningProcessIds {
    param([int]$Port)
    try {
        return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique)
    }
    catch {
        return @()
    }
}

function Stop-ListenersOnPort {
    param(
        [int]$Port,
        [string]$Reason
    )
    foreach ($processId in Get-ListeningProcessIds -Port $Port) {
        if ($processId -and $processId -ne $PID) {
            Write-Warn "Stopping process $processId listening on port $Port ($Reason)"
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
                $oldErrorActionPreference = $ErrorActionPreference
                try {
                    $ErrorActionPreference = "Continue"
                    & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
                }
                finally {
                    $ErrorActionPreference = $oldErrorActionPreference
                }
                if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
                    Write-Warn "Process $processId could not be stopped; a fallback port will be used if needed"
                }
            }
        }
    }
}

function Test-PortBindable {
    param([int]$Port)
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $Port)
        $listener.Server.ExclusiveAddressUse = $true
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($listener) {
            try {
                $listener.Stop()
            }
            catch {
            }
        }
    }
}

function Test-PortAvailable {
    param([int]$Port)
    if (@(Get-ListeningProcessIds -Port $Port).Count -gt 0) {
        return $false
    }
    return (Test-PortBindable -Port $Port)
}

function Find-AvailablePort {
    param([int[]]$Candidates)
    foreach ($candidate in $Candidates) {
        if (Test-PortAvailable -Port $candidate) {
            return $candidate
        }
    }
    for ($port = 18000; $port -lt 18100; $port++) {
        if (Test-PortAvailable -Port $port) {
            return $port
        }
    }
    Stop-WithError "No available fallback port found in 18000-18099."
}

function Ensure-ApiPort {
    Stop-ListenersOnPort -Port $ApiPort -Reason "required by darkweb collector API"
    Start-Sleep -Milliseconds 500
    if (Test-PortAvailable -Port $ApiPort) {
        return
    }

    $fallback = Find-AvailablePort -Candidates @(18000, 18001, 18002, 18003, 18004, 18005)
    Write-Warn "Port $ApiPort is occupied by a process that could not be stopped; using API port $fallback"
    Set-ApiPort -Port $fallback
}

function Ensure-FrontendPort {
    Stop-ListenersOnPort -Port $FrontendPort -Reason "required by darkweb dashboard"
    Start-Sleep -Milliseconds 500
    if (Test-PortAvailable -Port $FrontendPort) {
        return
    }

    $fallback = Find-AvailablePort -Candidates @(5174, 5175, 5176, 5177, 5178, 5179)
    Write-Warn "Port $FrontendPort is occupied by a process that could not be stopped; using frontend port $fallback"
    Set-FrontendPort -Port $fallback
}

function Get-ServiceRecords {
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return @()
    }
    $content = Get-Content -LiteralPath $PidFile -Raw
    if (-not $content.Trim()) {
        return @()
    }
    $records = $content | ConvertFrom-Json
    if ($records -is [array]) {
        return $records
    }
    return @($records)
}

function Test-ManagedServicesRunning {
    $requiredNames = @("api", "frontend", "worker-seed", "worker-detail", "scheduler", "vuln-sync")
    for ($index = 1; $index -le $BrowserConcurrency; $index++) {
        $requiredNames += "worker-browser-$index"
    }
    $records = @(Get-ServiceRecords)
    foreach ($name in $requiredNames) {
        $record = $records | Where-Object { $_.name -eq $name } | Select-Object -First 1
        if (-not $record) {
            return $false
        }
        if (-not (Test-ProcessRunning -ProcessId ([int]$record.pid))) {
            return $false
        }
    }
    return $true
}

function Test-DarkwebStackReady {
    Load-RuntimePorts
    if (-not (Test-ManagedServicesRunning)) {
        return $false
    }
    if (-not (Test-RedisReady)) {
        return $false
    }
    if (-not (Test-DarkwebApiReady)) {
        return $false
    }
    if (-not (Test-DarkwebFrontendReady)) {
        return $false
    }
    return $true
}

function Save-ServiceRecords {
    param([array]$Records)
    Ensure-Directory $RuntimeDir
    $Records | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $PidFile -Encoding UTF8
}

function Test-ProcessRunning {
    param([int]$ProcessId)
    return [bool](Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Get-ProcessRows {
    try {
        return @(Get-CimInstance Win32_Process -ErrorAction Stop)
    }
    catch {
        return @(Get-WmiObject Win32_Process -ErrorAction SilentlyContinue)
    }
}

function New-ProcessRowMap {
    param([object[]]$ProcessRows)
    $map = @{}
    foreach ($row in $ProcessRows) {
        if ($row -and $row.ProcessId) {
            $map[[int]$row.ProcessId] = $row
        }
    }
    return $map
}

function Invoke-TaskKill {
    param(
        [int]$ProcessId,
        [switch]$Tree
    )
    $arguments = @("/PID", "$ProcessId", "/F")
    if ($Tree) {
        $arguments += "/T"
    }
    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & taskkill.exe @arguments 2>$null | Out-Null
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
}

function Stop-ProcessTree {
    param(
        [int]$ProcessId,
        [object[]]$ProcessRows = $null,
        [hashtable]$ProcessRowMap = $null,
        [string]$Label = "process"
    )
    if (-not $ProcessId -or $ProcessId -eq $PID) {
        return
    }
    if ($null -eq $ProcessRows) {
        $ProcessRows = @(Get-ProcessRows)
    }
    if ($null -eq $ProcessRowMap) {
        $ProcessRowMap = New-ProcessRowMap -ProcessRows $ProcessRows
    }

    $children = @($ProcessRows | Where-Object { [int]$_.ParentProcessId -eq $ProcessId })
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId) -ProcessRows $ProcessRows -ProcessRowMap $ProcessRowMap -Label "child process"
    }

    if (Test-ProcessRunning -ProcessId $ProcessId) {
        Write-Info "Stopping $Label pid $ProcessId"
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 150
        if (Test-ProcessRunning -ProcessId $ProcessId) {
            Invoke-TaskKill -ProcessId $ProcessId -Tree
        }
    }
}

function Test-ProjectManagedCommandLine {
    param([string]$CommandLine)
    if (-not $CommandLine) {
        return $false
    }

    $projectProcessPattern = [regex]::Escape($ProjectRoot)
    if ($CommandLine -notmatch $projectProcessPattern) {
        return $false
    }

    $markers = @(
        "serve_api.py",
        "crawl.py",
        "darkweb_collector.celery_app",
        "celery",
        "node_modules\.bin",
        "vite\bin\vite.js",
        "npm-cli.js",
        "npm run dev"
    )
    return [bool]($markers | Where-Object { $CommandLine -like "*$_*" } | Select-Object -First 1)
}

function Test-ProjectManagedProcess {
    param(
        [object]$ProcessRow,
        [hashtable]$ProcessRowMap
    )
    if ($null -eq $ProcessRow) {
        return $false
    }
    if (Test-ProjectManagedCommandLine -CommandLine $ProcessRow.CommandLine) {
        return $true
    }

    $seen = New-Object "System.Collections.Generic.HashSet[int]"
    $parentId = [int]$ProcessRow.ParentProcessId
    while ($parentId -gt 0 -and $seen.Add($parentId)) {
        if ($null -eq $ProcessRowMap -or -not $ProcessRowMap.ContainsKey($parentId)) {
            break
        }
        $parent = $ProcessRowMap[$parentId]
        if ($null -eq $parent) {
            break
        }
        if (Test-ProjectManagedCommandLine -CommandLine $parent.CommandLine) {
            return $true
        }
        $parentId = [int]$parent.ParentProcessId
    }

    return $false
}

function Get-ProjectManagedProcessRows {
    param(
        [object[]]$ProcessRows,
        [hashtable]$ProcessRowMap
    )
    $candidateIds = New-Object "System.Collections.Generic.HashSet[int]"
    foreach ($row in $ProcessRows) {
        if ($row -and (Test-ProjectManagedCommandLine -CommandLine $row.CommandLine)) {
            $null = $candidateIds.Add([int]$row.ProcessId)
            $parentId = [int]$row.ParentProcessId
            if ($parentId -gt 0) {
                $null = $candidateIds.Add($parentId)
            }
        }
    }

    foreach ($processId in $candidateIds) {
        if ($ProcessRowMap.ContainsKey($processId)) {
            $ProcessRowMap[$processId]
        }
    }
}

function Stop-ProjectListenersOnPort {
    param(
        [int]$Port,
        [string]$Reason
    )
    $processRows = @(Get-ProcessRows)
    $processRowMap = New-ProcessRowMap -ProcessRows $processRows
    foreach ($processId in Get-ListeningProcessIds -Port $Port) {
        if (-not $processId -or $processId -eq $PID) {
            continue
        }
        $processRow = if ($processRowMap.ContainsKey([int]$processId)) { $processRowMap[[int]$processId] } else { $null }
        if (Test-ProjectManagedProcess -ProcessRow $processRow -ProcessRowMap $processRowMap) {
            Write-Warn "Stopping project process $processId listening on port $Port ($Reason)"
            Stop-ProcessTree -ProcessId ([int]$processId) -ProcessRows $processRows -ProcessRowMap $processRowMap -Label "port $Port listener"
        }
    }
}

function New-ServiceCommand {
    param(
        [string]$WorkingDirectory,
        [string]$Body,
        [string]$LogPath
    )

    $quotedWorkDir = Quote-PS $WorkingDirectory
    $quotedLog = Quote-PS $LogPath
    return @"
`$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $quotedWorkDir
`$env:Path = $(Quote-PS $env:Path)
`$env:REDIS_URL = $(Quote-PS $RedisUrl)
`$env:DARKWEB_API_HOST = '0.0.0.0'
`$env:DARKWEB_API_PORT = $(Quote-PS ([string]$ApiPort))
`$env:DARKWEB_API_TARGET = $(Quote-PS $ApiBaseUrl)
`$env:VITE_API_TARGET = $(Quote-PS $ApiBaseUrl)
`$env:DARKWEB_FRONTEND_PORT = $(Quote-PS ([string]$FrontendPort))
`$env:DARKWEB_FRONTEND_URL = $(Quote-PS $FrontendUrl)
`$env:VITE_FRONTEND_PORT = $(Quote-PS ([string]$FrontendPort))
`$env:PYTHONPATH = $(Quote-PS (Join-Path $CollectorRoot "src"))
`$env:DARKWEB_COLLECTOR_DB_PATH = $(Quote-PS $CollectorDbPath)
`$env:DARKWEB_COLLECTOR_SITES_FILE = $(Quote-PS $CollectorSitesFile)
`$env:DARKWEB_COLLECTOR_OUTPUT_ROOT = $(Quote-PS $CollectorOutputRoot)
`$env:DARKWEB_BROWSER_CONCURRENCY = $(Quote-PS ([string]$BrowserConcurrency))
`$env:NPM_CONFIG_CACHE = $(Quote-PS (Join-Path $DefaultUserDataDir "npm-cache"))
$Body *>> $quotedLog
"@
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [string]$Body
    )

    $powerShell = Resolve-PowerShellCommand
    $logPath = Join-Path $LogDir "$Name.log"
    if (Test-Path -LiteralPath $logPath) {
        try {
            Remove-Item -LiteralPath $logPath -Force -ErrorAction Stop
        }
        catch {
            $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $logPath = Join-Path $LogDir "$Name-$stamp.log"
            Write-Warn "Log file $Name.log is locked; using $([System.IO.Path]::GetFileName($logPath))"
        }
    }
    $command = New-ServiceCommand -WorkingDirectory $WorkingDirectory -Body $Body -LogPath $logPath
    $process = Start-Process -FilePath $powerShell -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $command
    ) -WindowStyle Hidden -PassThru

    return [pscustomobject]@{
        name = $Name
        pid = $process.Id
        log = $logPath
        started_at = (Get-Date).ToString("s")
    }
}

function Ensure-PythonRuntime {
    $python = Resolve-PythonExe
    if ($python) {
        return $python
    }

    Install-WingetPackage -PackageId "Python.Python.3.12" -DisplayName "Python 3.12" -Override "InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1"
    $python = Resolve-PythonExe
    if (-not $python) {
        Stop-WithError "Python was installed but python.exe is still not available. Reopen the terminal and run darkweb again."
    }
    return $python
}

function Test-PythonExe {
    param([string]$PythonPath)
    if (-not $PythonPath) {
        return $false
    }
    try {
        & $PythonPath -c "import sys, venv, ensurepip; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Resolve-PythonExe {
    $python = Resolve-WorkingCommand -Names @("python.exe", "python") -Arguments @("-c", "import sys, venv, ensurepip; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)")
    if ($python) {
        return $python
    }

    $candidates = @()
    $roots = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python"),
        ([Environment]::GetEnvironmentVariable("ProgramFiles")),
        ([Environment]::GetEnvironmentVariable("ProgramFiles(x86)"))
    )
    foreach ($root in $roots) {
        if ($root -and (Test-Path -LiteralPath $root)) {
            $candidates += @(Get-ChildItem -LiteralPath $root -Filter "Python3*" -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending |
                ForEach-Object { Join-Path $_.FullName "python.exe" })
        }
    }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ((Test-Path -LiteralPath $candidate) -and (Test-PythonExe $candidate)) {
            return $candidate
        }
    }

    $pyLauncher = Resolve-OptionalCommandPath @("py.exe", "py")
    if ($pyLauncher) {
        try {
            $resolved = & $pyLauncher -3 -c "import sys, venv, ensurepip; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath $resolved.Trim()) -and (Test-PythonExe $resolved.Trim())) {
                return $resolved.Trim()
            }
        }
        catch {
        }
    }
    return $null
}

function Resolve-NodeExe {
    $node = Resolve-WorkingCommand -Names @("node.exe", "node") -Arguments @("--version")
    if ($node) {
        return $node
    }

    $programFiles = [Environment]::GetEnvironmentVariable("ProgramFiles")
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $programW6432 = [Environment]::GetEnvironmentVariable("ProgramW6432")
    $candidates = @()
    foreach ($root in @($programFiles, $programW6432, $programFilesX86)) {
        if ($root) {
            $candidates += (Join-Path $root "nodejs\node.exe")
        }
    }
    $localPrograms = Join-Path $LocalAppDataRoot "Programs"
    $candidates += (Join-Path $localPrograms "nodejs\node.exe")

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ((Test-Path -LiteralPath $candidate)) {
            & $candidate --version *> $null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        }
    }
    return $null
}

function Ensure-NodeRuntime {
    $script:NodeExePath = ""
    $script:NodeBinDir = ""
    $node = Resolve-NodeExe
    if (-not $node) {
        Install-WingetPackage -PackageId "OpenJS.NodeJS.LTS" -DisplayName "Node.js LTS"
        $node = Resolve-NodeExe
    }
    if (-not $node) {
        Stop-WithError "Node.js was installed but node.exe is still not available. Reopen the terminal and run darkweb again."
    }

    $nodeDir = Split-Path -Parent $node
    $script:NodeExePath = $node
    $script:NodeBinDir = $nodeDir
    Add-ProcessPathEntry $nodeDir
    Add-UserPathEntry $nodeDir

    & $node -e "const major = Number(process.versions.node.split('.')[0]); process.exit(major >= 18 ? 0 : 1)" *> $null
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Node.js at $node is too old or cannot run. Install Node.js 18 LTS or newer."
    }

    $npm = Join-Path $nodeDir "npm.cmd"
    if (-not (Test-Path -LiteralPath $npm)) {
        $npm = Resolve-WorkingCommand -Names @("npm.cmd", "npm") -Arguments @("--version")
    }
    if (-not $npm) {
        Stop-WithError "Node.js is available at $node, but npm.cmd was not found. Reinstall Node.js LTS and run darkweb again."
    }
    & $npm --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "npm.cmd exists at $npm, but it cannot run correctly."
    }
    return $npm
}

function Resolve-RedisServerCommand {
    $redisServer = Resolve-OptionalCommandPath @("redis-server.exe", "redis-server")
    if ($redisServer) {
        return $redisServer
    }

    $memurai = Resolve-OptionalCommandPath @("memurai.exe", "memurai")
    if ($memurai) {
        return $memurai
    }

    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $candidates = @()
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles "Memurai\memurai.exe")
        $candidates += (Join-Path $env:ProgramFiles "Redis\redis-server.exe")
    }
    if ($programFilesX86) {
        $candidates += (Join-Path $programFilesX86 "Memurai\memurai.exe")
        $candidates += (Join-Path $programFilesX86 "Redis\redis-server.exe")
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return $null
}

function Start-RedisServiceIfAvailable {
    $services = @(Get-Service -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -like "*Memurai*" -or
        $_.DisplayName -like "*Memurai*" -or
        $_.Name -like "*Redis*" -or
        $_.DisplayName -like "*Redis*"
    })
    foreach ($service in $services) {
        if ($service.Status -ne "Running") {
            try {
                Write-Info "Starting Redis-compatible service: $($service.Name)"
                Start-Service -Name $service.Name -ErrorAction Stop
            }
            catch {
                Write-Warn "Could not start service $($service.Name): $($_.Exception.Message)"
            }
        }
        if (Wait-ForRedis -TimeoutSeconds 10) {
            return $true
        }
    }
    return $false
}

function Start-DockerRedisIfAvailable {
    $endpoint = Get-RedisEndpoint
    if (-not $endpoint.IsLocal) {
        return $false
    }

    $docker = Resolve-DockerCommand
    if (-not $docker) {
        return $false
    }

    & $docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Docker was found, but the Docker engine is not running"
        return $false
    }

    $containerName = "darkweb-redis"
    $running = (& $docker ps --filter "name=^/${containerName}$" --format "{{.Names}}" 2>$null) -join ""
    if ($running -eq $containerName) {
        return (Wait-ForRedis -TimeoutSeconds 15)
    }

    $existing = (& $docker ps -a --filter "name=^/${containerName}$" --format "{{.Names}}" 2>$null) -join ""
    if ($existing -eq $containerName) {
        Write-Info "Starting Redis Docker container: $containerName"
        & $docker start $containerName *> $null
    }
    else {
        Write-Info "Creating Redis Docker container: $containerName"
        & $docker run -d --name $containerName -p "$($endpoint.Port):6379" redis:7-alpine *> $null
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Docker could not start a Redis container"
        return $false
    }
    return (Wait-ForRedis -TimeoutSeconds $ServiceWaitSeconds)
}

function Ensure-RedisRuntime {
    if (Test-RedisReady) {
        return
    }
    $endpoint = Get-RedisEndpoint
    if (-not $endpoint.IsLocal) {
        Stop-WithError "REDIS_URL points to $RedisUrl, but it is not reachable. Start that Redis instance or change REDIS_URL."
    }
    if (Start-RedisServiceIfAvailable) {
        return
    }
    if (Start-DockerRedisIfAvailable) {
        return
    }
    if (Resolve-RedisServerCommand) {
        return
    }

    Install-WingetPackage -PackageId "Memurai.MemuraiDeveloper" -DisplayName "Memurai Developer (Redis-compatible server)"
    Update-ProcessPathFromRegistry
    if (Start-RedisServiceIfAvailable) {
        return
    }
    if (Resolve-RedisServerCommand) {
        return
    }

    Stop-WithError "Memurai was installed, but no Redis-compatible service or executable could be found."
}

function Register-DarkwebCommand {
    if ($Action -eq "register") {
        Load-RuntimePorts
    }
    Ensure-Directory $CommandBinDir
    $commandText = @"
@echo off
set "COLLECTOR_ROOT=%DARKWEB_COLLECTOR_ROOT%"
if "%COLLECTOR_ROOT%"=="" set "COLLECTOR_ROOT=$CollectorRoot"
set "DARKWEB_API_PORT=$ApiPort"
set "DARKWEB_API_TARGET=$ApiBaseUrl"
set "VITE_API_TARGET=$ApiBaseUrl"
set "DARKWEB_FRONTEND_PORT=$FrontendPort"
set "DARKWEB_FRONTEND_URL=$FrontendUrl"
set "VITE_FRONTEND_PORT=$FrontendPort"
if not exist "%COLLECTOR_ROOT%\scripts\start_all_services_windows.ps1" (
  echo [ERROR] DARKWEB_COLLECTOR_ROOT is not valid. Run .\darkweb.cmd register from the project root.
  exit /b 1
)
if "%~1"=="" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%COLLECTOR_ROOT%\scripts\start_all_services_windows.ps1" start
) else (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%COLLECTOR_ROOT%\scripts\start_all_services_windows.ps1" %*
)
"@
    Set-Content -LiteralPath $DarkwebCommandPath -Value $commandText -Encoding ASCII
    Add-UserPathEntry $CommandBinDir

    Set-UserEnv -Name "DARKWEB_PROJECT_ROOT" -Value $ProjectRoot
    Set-UserEnv -Name "DARKWEB_HOME" -Value $ProjectRoot
    Set-UserEnv -Name "DARKWEB_COLLECTOR_ROOT" -Value $CollectorRoot
    Set-UserEnv -Name "DARKWEB_DASHBOARD_ROOT" -Value $DashboardRoot
    Set-UserEnv -Name "DARKWEB_COLLECTOR_DB_PATH" -Value $CollectorDbPath
    Set-UserEnv -Name "DARKWEB_COLLECTOR_SITES_FILE" -Value $CollectorSitesFile
    Set-UserEnv -Name "DARKWEB_COLLECTOR_OUTPUT_ROOT" -Value $CollectorOutputRoot
    Set-UserEnv -Name "REDIS_URL" -Value $RedisUrl
    Set-UserEnv -Name "DARKWEB_API_PORT" -Value ([string]$ApiPort)
    Set-UserEnv -Name "DARKWEB_API_TARGET" -Value $ApiBaseUrl
    Set-UserEnv -Name "DARKWEB_FRONTEND_PORT" -Value ([string]$FrontendPort)
    Set-UserEnv -Name "DARKWEB_FRONTEND_URL" -Value $FrontendUrl
    Write-Info "Registered darkweb command: $DarkwebCommandPath"
}

function Test-CollectorVenv {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        return $false
    }
    try {
        & $VenvPython -c "import sys, pathlib, pip; raise SystemExit(0 if pathlib.Path(sys.executable).exists() and pathlib.Path(sys.prefix).exists() else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Ensure-CollectorVenv {
    $python = Ensure-PythonRuntime
    if ((Test-Path -LiteralPath $VenvDir) -and -not (Test-CollectorVenv)) {
        Write-Warn "Existing collector virtual environment is not usable on this machine; rebuilding it"
        Remove-GeneratedDirectory -Path $VenvDir -AllowedRoot $CollectorRoot
    }
    if (-not (Test-CollectorVenv)) {
        Write-Info "Creating Python virtual environment"
        & $python -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) {
            Stop-WithError "Failed to create Python virtual environment."
        }
    }
}

function Test-CollectorDependencies {
    try {
        & $VenvPython -c "import celery, redis, playwright, fastapi, uvicorn, pycountry, babel" *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Ensure-CollectorDependencies {
    $requirementsPath = Join-Path $CollectorRoot "requirements.txt"
    $expectedHash = Get-FileHashText $requirementsPath
    $currentHash = if (Test-Path -LiteralPath $RequirementsStamp) { (Get-Content -LiteralPath $RequirementsStamp -Raw).Trim() } else { "" }
    if ($expectedHash -eq $currentHash -and (Test-CollectorDependencies)) {
        return
    }

    Write-Info "Installing collector Python dependencies"
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Failed to upgrade pip."
    }
    & $VenvPython -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Failed to install Python requirements."
    }
    Set-Content -LiteralPath $RequirementsStamp -Value $expectedHash -Encoding ASCII
}

function Test-PlaywrightBrowsers {
    try {
        $code = "from pathlib import Path; from playwright.sync_api import sync_playwright; p = sync_playwright().start(); paths = [Path(p.chromium.executable_path), Path(p.firefox.executable_path)]; p.stop(); raise SystemExit(0 if all(path.exists() for path in paths) else 1)"
        & $VenvPython -c $code *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Ensure-PlaywrightRuntime {
    if ((Test-Path -LiteralPath $PlaywrightStamp) -and (Test-PlaywrightBrowsers)) {
        return
    }
    Write-Info "Installing Playwright browser runtimes"
    & $VenvPython -m playwright install chromium firefox
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Failed to install Playwright browser runtimes."
    }
    New-Item -ItemType File -Path $PlaywrightStamp -Force | Out-Null
}

function Ensure-DashboardDependencies {
    $npm = Ensure-NodeRuntime
    $packageLockPath = Join-Path $DashboardRoot "package-lock.json"
    $expectedHash = Get-FileHashText $packageLockPath
    $currentHash = if (Test-Path -LiteralPath $PackageLockStamp) { (Get-Content -LiteralPath $PackageLockStamp -Raw).Trim() } else { "" }
    $viteBin = Join-Path $DashboardRoot "node_modules\.bin\vite.cmd"
    if ((Test-Path -LiteralPath $viteBin) -and $expectedHash -eq $currentHash) {
        return
    }
    Write-Info "Installing dashboard dependencies"
    $npmCache = Join-Path $DefaultUserDataDir "npm-cache"
    Ensure-Directory $npmCache
    $env:NPM_CONFIG_CACHE = $npmCache
    if ($script:NodeBinDir) {
        Add-ProcessPathEntry $script:NodeBinDir
    }
    Push-Location $DashboardRoot
    try {
        if (Test-Path -LiteralPath $packageLockPath) {
            & $npm ci
        }
        else {
            & $npm install
        }
        if ($LASTEXITCODE -ne 0) {
            Stop-WithError "Failed to install dashboard dependencies."
        }
    }
    finally {
        Pop-Location
    }
    Ensure-Directory (Split-Path -Parent $PackageLockStamp)
    Set-Content -LiteralPath $PackageLockStamp -Value $expectedHash -Encoding ASCII
}

function Ensure-RuntimeDatabase {
    Ensure-Directory (Split-Path -Parent $CollectorDbPath)
    Ensure-Directory $CollectorOutputRoot
    Copy-MissingOutputArtifacts
    $pythonCode = "from pathlib import Path; import sys; root = Path(sys.argv[1]); target = Path(sys.argv[2]); src = root / 'src'; sys.path.insert(0, str(src)); from darkweb_collector.db import connect; connection = connect(target); connection.commit(); connection.close()"
    & $VenvPython -c $pythonCode $CollectorRoot $CollectorDbPath
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Failed to initialize collector database."
    }
}

function Copy-MissingOutputArtifacts {
    $sourceOutputRoot = Join-Path $CollectorRoot "output"
    if (-not (Test-Path -LiteralPath $sourceOutputRoot)) {
        return
    }

    Ensure-Directory $CollectorOutputRoot
    $resolvedSource = (Resolve-Path -LiteralPath $sourceOutputRoot).Path
    $resolvedTarget = (Resolve-Path -LiteralPath $CollectorOutputRoot).Path
    if ($resolvedSource.TrimEnd("\") -ieq $resolvedTarget.TrimEnd("\")) {
        return
    }

    $copied = 0
    $sourceFiles = @(Get-ChildItem -LiteralPath $resolvedSource -Recurse -File -ErrorAction SilentlyContinue)
    foreach ($file in $sourceFiles) {
        $relativePath = $file.FullName.Substring($resolvedSource.Length).TrimStart([char[]]@("\", "/"))
        if (-not $relativePath) {
            continue
        }
        $targetPath = Join-Path $resolvedTarget $relativePath
        if (Test-Path -LiteralPath $targetPath) {
            continue
        }
        Ensure-Directory (Split-Path -Parent $targetPath)
        Copy-Item -LiteralPath $file.FullName -Destination $targetPath
        $copied += 1
    }
    if ($copied -gt 0) {
        Write-Info "Copied $copied existing collector output artifact(s) into runtime output root"
    }
}

function Ensure-SiteConfigsLoad {
    Ensure-Directory $RuntimeDir
    $checkerPath = Join-Path $RuntimeDir "check_sites.py"
    $pythonCode = @"
from pathlib import Path
import sys
root = Path(sys.argv[1])
sites_file = Path(sys.argv[2])
src = root / "src"
sys.path.insert(0, str(src))
from darkweb_collector.config import load_site_configs
from darkweb_collector.adapters.registry import get_adapter
configs = load_site_configs(sites_file)
if not configs:
    raise SystemExit("no site config found")
missing = []
for config in configs:
    try:
        get_adapter(config.site_name)
    except Exception as exc:
        missing.append(f"{config.site_name}: {exc}")
if missing:
    raise SystemExit("adapter missing for configured sites: " + "; ".join(missing))
print(",".join(config.site_name for config in configs))
"@
    Set-Content -LiteralPath $checkerPath -Value $pythonCode -Encoding UTF8
    $output = & $VenvPython $checkerPath $CollectorRoot $CollectorSitesFile
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Failed to load crawler site configuration from $CollectorSitesFile. $output"
    }
    Write-Info "Crawler sites loaded: $output"
}

function Ensure-Redis {
    if (Test-RedisReady) {
        Write-Info "Redis is already running"
        return $null
    }

    $endpoint = Get-RedisEndpoint
    if (-not $endpoint.IsLocal) {
        Stop-WithError "REDIS_URL points to $RedisUrl, but it is not reachable. Start that Redis instance or change REDIS_URL."
    }

    $redisServer = Resolve-RedisServerCommand
    if (-not $redisServer) {
        Stop-WithError "Redis is not running and redis-server was not found in PATH. Start Redis on 127.0.0.1:6379 or install Redis for Windows, Memurai, or Redis in WSL with port forwarding."
    }

    Write-Info "Starting Redis"
    $body = "& $(Quote-PS $redisServer) --port $($endpoint.Port)"
    $record = Start-ManagedProcess -Name "redis" -WorkingDirectory $CollectorRoot -Body $body
    if (-not (Wait-ForRedis -TimeoutSeconds $ServiceWaitSeconds)) {
        Stop-WithError "Redis did not become ready. Check $($record.log)."
    }
    return $record
}

function Ensure-RedisCanStart {
    Ensure-RedisRuntime
}

function Ensure-Environment {
    Invoke-TimedStep "Ensure-PythonRuntime" { Ensure-PythonRuntime | Out-Null }
    Invoke-TimedStep "Ensure-NodeRuntime" { Ensure-NodeRuntime | Out-Null }
    Invoke-TimedStep "Ensure-RedisCanStart" { Ensure-RedisCanStart }
    Invoke-TimedStep "Register-DarkwebCommand" { Register-DarkwebCommand }
    if (-not (Test-Path -LiteralPath (Join-Path $CollectorRoot "scripts\serve_api.py"))) {
        Stop-WithError "API launcher not found under collector scripts."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $DashboardRoot "package.json"))) {
        Stop-WithError "Dashboard package.json not found."
    }

    Ensure-Directory $RuntimeDir
    Ensure-Directory $LogDir
    Invoke-TimedStep "Ensure-CollectorVenv" { Ensure-CollectorVenv }
    Invoke-TimedStep "Ensure-CollectorDependencies" { Ensure-CollectorDependencies }
    Invoke-TimedStep "Ensure-PlaywrightRuntime" { Ensure-PlaywrightRuntime }
    Invoke-TimedStep "Ensure-DashboardDependencies" { Ensure-DashboardDependencies }
    Invoke-TimedStep "Ensure-RuntimeDatabase" { Ensure-RuntimeDatabase }
    Invoke-TimedStep "Ensure-SiteConfigsLoad" { Ensure-SiteConfigsLoad }
}

function Start-Services {
    if (Test-DarkwebStackReady) {
        Write-Info "Services already running"
        Write-Info "Frontend: $FrontendUrl"
        Write-Info "API jobs: $ApiJobsUrl"
        return
    }

    Ensure-Environment

    $existingRecords = @(Get-ServiceRecords | Where-Object { Test-ProcessRunning -ProcessId ([int]$_.pid) })
    if ($existingRecords.Count -gt 0) {
        Write-Warn "Existing $SessionName services are running; stopping them first"
        Stop-Services
    }

    # A previous run may have lost its PID file, or another dev server may
    # still occupy the fixed ports used by Vite's proxy. Clear those ports
    # when they are not serving this project's API/frontend.
    $originalApiPort = $ApiPort
    $originalFrontendPort = $FrontendPort
    Ensure-ApiPort
    Ensure-FrontendPort
    Save-RuntimePorts
    if ($ApiPort -ne $originalApiPort -or $FrontendPort -ne $originalFrontendPort) {
        Register-DarkwebCommand
    }

    $records = @()
    $redisRecord = Ensure-Redis
    if ($redisRecord) {
        $records += $redisRecord
    }

    $python = Quote-PS $VenvPython
    $null = Ensure-NodeRuntime
    $node = Quote-PS $script:NodeExePath
    $crawler = Quote-PS (Join-Path $CollectorRoot "scripts\crawl.py")
    $apiLauncher = Quote-PS (Join-Path $CollectorRoot "scripts\serve_api.py")
    $viteCli = Quote-PS (Join-Path $DashboardRoot "node_modules\vite\bin\vite.js")

    $records += Start-ManagedProcess -Name "api" -WorkingDirectory $CollectorRoot -Body "& $python $apiLauncher"
    if (-not (Wait-ForDarkwebApi -TimeoutSeconds $ServiceWaitSeconds)) {
        Write-Warn "Darkweb API did not return configured site health within ${ServiceWaitSeconds}s"
    }

    $records += Start-ManagedProcess -Name "frontend" -WorkingDirectory $DashboardRoot -Body "& $node $viteCli --host 0.0.0.0 --port $FrontendPort --strictPort"
    $records += Start-ManagedProcess -Name "worker-seed" -WorkingDirectory $CollectorRoot -Body "& $python -m celery -A darkweb_collector.celery_app:app worker -Q seed_http --concurrency 1 --prefetch-multiplier 1 --pool solo --loglevel info"
    $records += Start-ManagedProcess -Name "worker-detail" -WorkingDirectory $CollectorRoot -Body "& $python -m celery -A darkweb_collector.celery_app:app worker -Q detail_http --concurrency 1 --prefetch-multiplier 1 --pool solo --loglevel info"
    for ($index = 1; $index -le $BrowserConcurrency; $index++) {
        $records += Start-ManagedProcess -Name "worker-browser-$index" -WorkingDirectory $CollectorRoot -Body "& $python -m celery -A darkweb_collector.celery_app:app worker -Q browser_render --concurrency 1 --prefetch-multiplier 1 --pool solo --loglevel info"
    }
    $records += Start-ManagedProcess -Name "scheduler" -WorkingDirectory $CollectorRoot -Body "while (`$true) { Write-Host `"[`$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] enqueue-due`"; & $python $crawler enqueue-due; Start-Sleep -Seconds $SchedulerIntervalSeconds }"
    $records += Start-ManagedProcess -Name "vuln-sync" -WorkingDirectory $CollectorRoot -Body "while (`$true) { Write-Host `"[`$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] sync-public-vulns --limit $VulnSyncLimit`"; & $python $crawler sync-public-vulns --limit $VulnSyncLimit; Start-Sleep -Seconds $VulnSyncIntervalSeconds }"

    Save-ServiceRecords $records

    if (-not (Wait-ForDarkwebFrontend -TimeoutSeconds $ServiceWaitSeconds)) {
        Write-Warn "Darkweb frontend did not become ready within ${ServiceWaitSeconds}s"
    }

    Write-Info "Services started"
    Write-Info "Frontend: $FrontendUrl"
    Write-Info "API jobs: $ApiJobsUrl"
    Write-Info "Logs: $LogDir"
    Show-Status
}

function Stop-Services {
    $portsToClean = @($ApiPort, $FrontendPort)
    Load-RuntimePorts
    $runtimePortsToClean = @($ApiPort, $FrontendPort)
    $projectPortsToClean = @(8000, 5173)

    $records = @(Get-ServiceRecords)
    $processRows = @(Get-ProcessRows)
    $processRowMap = New-ProcessRowMap -ProcessRows $processRows
    foreach ($record in $records) {
        $pidValue = [int]$record.pid
        if (Test-ProcessRunning -ProcessId $pidValue) {
            Stop-ProcessTree -ProcessId $pidValue -ProcessRows $processRows -ProcessRowMap $processRowMap -Label $record.name
        }
    }

    Start-Sleep -Milliseconds 300
    $processRows = @(Get-ProcessRows)
    $processRowMap = New-ProcessRowMap -ProcessRows $processRows
    Get-ProjectManagedProcessRows -ProcessRows $processRows -ProcessRowMap $processRowMap |
        Sort-Object ProcessId -Descending |
        ForEach-Object {
            Stop-ProcessTree -ProcessId ([int]$_.ProcessId) -ProcessRows $processRows -ProcessRowMap $processRowMap -Label "project process"
        }

    foreach ($port in @($runtimePortsToClean | Where-Object { $_ -and [int]$_ -gt 0 } | Sort-Object -Unique)) {
        Stop-ListenersOnPort -Port ([int]$port) -Reason "darkweb runtime port cleanup"
    }
    foreach ($port in @($projectPortsToClean | Where-Object { $_ -and [int]$_ -gt 0 } | Sort-Object -Unique)) {
        Stop-ProjectListenersOnPort -Port ([int]$port) -Reason "darkweb stop cleanup"
    }

    if (Test-Path -LiteralPath $PidFile) {
        Remove-Item -LiteralPath $PidFile -Force
    }
    Write-Info "Services stopped"
}

function Show-Status {
    Load-RuntimePorts
    $records = @(Get-ServiceRecords)
    if ($records.Count -eq 0) {
        Write-Info "No PID file found for $SessionName"
    }
    else {
        foreach ($record in $records) {
            $pidValue = [int]$record.pid
            $state = if (Test-ProcessRunning -ProcessId $pidValue) { "up" } else { "down" }
            Write-Info "$($record.name): $state (pid $pidValue, log $($record.log))"
        }
    }

    if (Test-RedisReady) {
        Write-Info "redis: up"
    }
    else {
        Write-Info "redis: down"
    }

    if (Test-DarkwebApiReady) {
        Write-Info "api: up ($ApiJobsUrl)"
    }
    else {
        Write-Info "api: down or not this project's API ($ApiJobsUrl must return non-empty site_health)"
    }

    if (Test-DarkwebFrontendReady) {
        Write-Info "frontend: up ($FrontendUrl)"
    }
    else {
        Write-Info "frontend: down"
    }
}

switch ($Action) {
    "start" { Start-Services }
    "stop" { Stop-Services }
    "status" { Show-Status }
    "install" {
        Ensure-Environment
        Write-Info "Environment is ready. Run 'darkweb' to start the system."
    }
    "register" { Register-DarkwebCommand }
}
