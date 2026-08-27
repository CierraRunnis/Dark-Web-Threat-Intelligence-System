[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$ControlRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Path)).TrimEnd("\")
}

function Resolve-ControlRoot {
    if ($ControlRoot) { return Resolve-FullPath $ControlRoot }
    $configured = [string][Environment]::GetEnvironmentVariable("DARKWEB_UPDATE_STATE_DIR", "User")
    if (-not $configured) { $configured = [string]$env:DARKWEB_UPDATE_STATE_DIR }
    if ($configured) { return Resolve-FullPath $configured }
    $local = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $env:USERPROFILE "AppData\Local" }
    return Resolve-FullPath (Join-Path $local "DarkWebThreatIntel")
}

function Test-ProjectRoot([string]$Path) {
    if (-not $Path) { return $false }
    $root = Resolve-FullPath $Path
    return (
        (Test-Path -LiteralPath (Join-Path $root "version.json") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $root "darkweb_collector\scripts\start_all_services_windows.ps1") -PathType Leaf)
    )
}

function Resolve-ProjectRoot([string]$StateRoot) {
    if ($ProjectRoot) {
        if (-not (Test-ProjectRoot $ProjectRoot)) { throw "ProjectRoot is not a Darkweb release: $ProjectRoot" }
        return Resolve-FullPath $ProjectRoot
    }

    $candidates = [System.Collections.Generic.List[string]]::new()
    $candidates.Add((Get-Location).Path)
    $candidates.Add((Resolve-FullPath (Join-Path $PSScriptRoot "..")))
    $installationPath = Join-Path $StateRoot "installation.json"
    if (Test-Path -LiteralPath $installationPath -PathType Leaf) {
        try {
            $installation = Get-Content -LiteralPath $installationPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($installation.current_root) { $candidates.Add([string]$installation.current_root) }
        }
        catch {
            throw "Installation state is invalid: $installationPath"
        }
    }
    $registeredProject = [string][Environment]::GetEnvironmentVariable("DARKWEB_PROJECT_ROOT", "User")
    if ($registeredProject) { $candidates.Add($registeredProject) }
    $registeredCollector = [string][Environment]::GetEnvironmentVariable("DARKWEB_COLLECTOR_ROOT", "User")
    if ($registeredCollector) { $candidates.Add((Join-Path $registeredCollector "..")) }

    foreach ($candidate in $candidates) {
        if (Test-ProjectRoot $candidate) { return Resolve-FullPath $candidate }
    }
    throw "Could not locate the active Darkweb release. Run this script from the extracted release directory or pass -ProjectRoot."
}

function Get-ProcessCommandLine([int]$ProcessId) {
    try {
        $row = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
        return [string]$row.CommandLine
    }
    catch {
        try {
            $row = Get-WmiObject Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
            return [string]$row.CommandLine
        }
        catch {
            return ""
        }
    }
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    [IO.File]::WriteAllText($Path, $Content, [Text.UTF8Encoding]::new($false))
}

$resolvedControlRoot = Resolve-ControlRoot
$resolvedProjectRoot = Resolve-ProjectRoot $resolvedControlRoot
$versionPath = Join-Path $resolvedProjectRoot "version.json"
$version = Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$version.version -notmatch '^v20260827(?:\.|$)') {
    throw "This transition repair only supports v20260827 releases; current version is $($version.version)"
}

$launcherPath = Join-Path $resolvedProjectRoot "darkweb_collector\scripts\start_all_services_windows.ps1"
$original = [IO.File]::ReadAllText($launcherPath)
$newline = if ($original.Contains("`r`n")) { "`r`n" } else { "`n" }
$content = $original.Replace("`r`n", "`n")

$utilityMarker = 'Get-FileHash is unavailable in the current PowerShell environment.'
if (-not $content.Contains($utilityMarker)) {
    $anchor = '$ErrorActionPreference = "Stop"' + "`n"
    if (-not $content.Contains($anchor)) { throw "Could not locate the PowerShell bootstrap anchor" }
    $utilityBlock = @'
if (-not (Get-Command Get-FileHash -ErrorAction SilentlyContinue)) {
    $utilityModules = @(
        (Join-Path $PSHOME "Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1"),
        (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1")
    )
    foreach ($module in $utilityModules) {
        if (Test-Path -LiteralPath $module -PathType Leaf) {
            Import-Module -Name $module -ErrorAction SilentlyContinue
        }
        if (Get-Command Get-FileHash -ErrorAction SilentlyContinue) { break }
    }
}
if (-not (Get-Command Get-FileHash -ErrorAction SilentlyContinue)) {
    throw "Get-FileHash is unavailable in the current PowerShell environment."
}
'@
    $utilityBlock = $utilityBlock.Replace("`r`n", "`n")
    $content = $content.Replace($anchor, $anchor + $utilityBlock + "`n")
}

$preserveMarker = 'Preserving active update controller pid'
if (-not $content.Contains($preserveMarker)) {
    $oldLoop = @'
    $children = @($ProcessRows | Where-Object { [int]$_.ParentProcessId -eq $ProcessId })
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId) -ProcessRows $ProcessRows -ProcessRowMap $ProcessRowMap -Label "child process"
    }
'@
    $newLoop = @'
    $children = @($ProcessRows | Where-Object { [int]$_.ParentProcessId -eq $ProcessId })
    foreach ($child in $children) {
        if ($child.CommandLine -like "*run_self_update.py*") {
            Write-Info "Preserving active update controller pid $($child.ProcessId)"
            continue
        }
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId) -ProcessRows $ProcessRows -ProcessRowMap $ProcessRowMap -Label "child process"
    }
'@
    $oldLoop = $oldLoop.Replace("`r`n", "`n")
    $newLoop = $newLoop.Replace("`r`n", "`n")
    if (-not $content.Contains($oldLoop)) { throw "Could not locate the process-tree stop block" }
    $content = $content.Replace($oldLoop, $newLoop)
}

$portsMarker = '[Text.UTF8Encoding]::new($false)'
if (-not $content.Contains($portsMarker)) {
    $oldPorts = @'
    [pscustomobject]@{
        api_port = $ApiPort
        api_base_url = $ApiBaseUrl
        frontend_port = $FrontendPort
        frontend_url = $FrontendUrl
        updated_at = (Get-Date).ToString("s")
    } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $RuntimePortsFile -Encoding UTF8
'@
    $newPorts = @'
    $payload = [pscustomobject]@{
        api_port = $ApiPort
        api_base_url = $ApiBaseUrl
        frontend_port = $FrontendPort
        frontend_url = $FrontendUrl
        updated_at = (Get-Date).ToString("s")
    } | ConvertTo-Json -Depth 3
    [IO.File]::WriteAllText($RuntimePortsFile, $payload + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
'@
    $oldPorts = $oldPorts.Replace("`r`n", "`n")
    $newPorts = $newPorts.Replace("`r`n", "`n")
    if (-not $content.Contains($oldPorts)) { throw "Could not locate the runtime ports writer" }
    $content = $content.Replace($oldPorts, $newPorts)
}

$parseErrors = $null
[Management.Automation.Language.Parser]::ParseInput($content, [ref]$null, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count) {
    throw "Patched launcher did not pass PowerShell parsing: $($parseErrors[0].Message)"
}

$backupPath = "$launcherPath.pre-v20260827.2.0.bak"
if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
    Copy-Item -LiteralPath $launcherPath -Destination $backupPath
}
if ($content -ne $original.Replace("`r`n", "`n")) {
    $temporary = "$launcherPath.repair-$PID"
    try {
        Write-Utf8NoBom $temporary ($content.Replace("`n", $newline))
        Move-Item -LiteralPath $temporary -Destination $launcherPath -Force
    }
    finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

$statusPath = Join-Path $resolvedControlRoot "update-status.json"
if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
    $status = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$status.status -in @("queued", "running")) {
        $processId = if ($status.pid) { [int]$status.pid } else { 0 }
        $commandLine = if ($processId -gt 0) { Get-ProcessCommandLine $processId } else { "" }
        if ($commandLine -like "*run_self_update.py*") {
            throw "An update controller is still running (pid $processId). Wait for it to finish before repairing."
        }
        $status | Add-Member -NotePropertyName pid -NotePropertyValue 0 -Force
        $status | Add-Member -NotePropertyName status -NotePropertyValue "failed" -Force
        $status | Add-Member -NotePropertyName stage -NotePropertyValue "failed" -Force
        $status | Add-Member -NotePropertyName message -NotePropertyValue "Windows update bootstrap repaired; retry the update" -Force
        $status | Add-Member -NotePropertyName error -NotePropertyValue "Previous update controller was not running" -Force
        $status | Add-Member -NotePropertyName updated -NotePropertyValue $false -Force
        $status | Add-Member -NotePropertyName finished_at -NotePropertyValue ([DateTimeOffset]::Now.ToString("o")) -Force
        $temporaryStatus = "$statusPath.repair-$PID"
        try {
            Write-Utf8NoBom $temporaryStatus (($status | ConvertTo-Json -Depth 10) + $newline)
            Move-Item -LiteralPath $temporaryStatus -Destination $statusPath -Force
        }
        finally {
            Remove-Item -LiteralPath $temporaryStatus -Force -ErrorAction SilentlyContinue
        }
    }
}

Write-Host "Windows update bootstrap repaired successfully."
Write-Host "Project: $resolvedProjectRoot"
Write-Host "Backup:  $backupPath"
Write-Host "You can now start the current version and click Check and Update again."
