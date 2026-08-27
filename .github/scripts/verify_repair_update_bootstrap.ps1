$ErrorActionPreference = "Stop"

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$sandbox = [IO.Path]::GetFullPath((Join-Path $temporaryRoot ("darkweb-update-repair-" + [Guid]::NewGuid().ToString("N"))))
if (-not $sandbox.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe repair-test directory"
}

New-Item -ItemType Directory -Path $sandbox -Force | Out-Null
try {
    $projectRoot = Join-Path $sandbox "project"
    $scriptDirectory = Join-Path $projectRoot "darkweb_collector\scripts"
    $controlRoot = Join-Path $sandbox "control"
    New-Item -ItemType Directory -Path $scriptDirectory,$controlRoot -Force | Out-Null

    $oldVersion = @(git -C $repositoryRoot show "v20260827:version.json") -join "`n"
    $oldLauncher = @(git -C $repositoryRoot show "v20260827:darkweb_collector/scripts/start_all_services_windows.ps1") -join "`n"
    if ($LASTEXITCODE -ne 0 -or -not $oldVersion -or -not $oldLauncher) {
        throw "Could not read the v20260827 release files"
    }
    [IO.File]::WriteAllText((Join-Path $projectRoot "version.json"), $oldVersion + "`n", [Text.UTF8Encoding]::new($false))
    $launcherPath = Join-Path $scriptDirectory "start_all_services_windows.ps1"
    [IO.File]::WriteAllText($launcherPath, $oldLauncher + "`n", [Text.UTF8Encoding]::new($false))

    $statePath = Join-Path $controlRoot "update-status.json"
    $state = [ordered]@{
        job_id = "stale-job"
        pid = 999999
        status = "running"
        stage = "stopping"
        message = "stale"
        updated = $false
    }
    [IO.File]::WriteAllText($statePath, ($state | ConvertTo-Json), [Text.UTF8Encoding]::new($false))

    $repair = Join-Path $repositoryRoot "scripts\repair_v20260827_update.ps1"
    & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -NoProfile -ExecutionPolicy Bypass -File $repair `
        -ProjectRoot $projectRoot -ControlRoot $controlRoot
    if ($LASTEXITCODE -ne 0) { throw "Transition repair failed" }

    $patched = [IO.File]::ReadAllText($launcherPath)
    foreach ($marker in @(
        "Get-FileHash is unavailable in the current PowerShell environment.",
        "Preserving active update controller pid",
        '[Text.UTF8Encoding]::new($false)'
    )) {
        if (-not $patched.Contains($marker)) { throw "Patched launcher is missing: $marker" }
    }
    $parseErrors = $null
    [Management.Automation.Language.Parser]::ParseInput($patched, [ref]$null, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count) { throw "Patched launcher did not parse: $($parseErrors[0].Message)" }

    $updatedState = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($updatedState.status -ne "failed" -or [int]$updatedState.pid -ne 0) {
        throw "Stale update state was not released"
    }
    $backupPath = "$launcherPath.pre-v20260827.2.0.bak"
    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) { throw "Launcher backup was not created" }

    $firstHash = (Get-FileHash -LiteralPath $launcherPath -Algorithm SHA256).Hash
    & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -NoProfile -ExecutionPolicy Bypass -File $repair `
        -ProjectRoot $projectRoot -ControlRoot $controlRoot
    if ($LASTEXITCODE -ne 0) { throw "Idempotent repair rerun failed" }
    $secondHash = (Get-FileHash -LiteralPath $launcherPath -Algorithm SHA256).Hash
    if ($firstHash -ne $secondHash) { throw "Repair was not idempotent" }
}
finally {
    $resolvedSandbox = [IO.Path]::GetFullPath($sandbox)
    if ($resolvedSandbox.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $resolvedSandbox) -like "darkweb-update-repair-*") {
        Remove-Item -LiteralPath $resolvedSandbox -Recurse -Force
    }
}

Write-Host "Windows transition repair checks passed."
