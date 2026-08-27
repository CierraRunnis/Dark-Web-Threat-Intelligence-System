$ErrorActionPreference = "Stop"

$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$configurator = Join-Path $repositoryRoot "darkweb_collector\scripts\configure_data_root_windows.ps1"
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$sandbox = [IO.Path]::GetFullPath((Join-Path $temporaryRoot ("darkweb-first-run-" + [Guid]::NewGuid().ToString("N"))))
if (-not $sandbox.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe first-run test directory"
}

New-Item -ItemType Directory -Path $sandbox -Force | Out-Null
try {
    foreach ($caseName in @("empty", "existing", "pending-migration")) {
        $caseRoot = Join-Path $sandbox $caseName
        $env:LOCALAPPDATA = Join-Path $caseRoot "local"
        $env:DARKWEB_UPDATE_STATE_DIR = Join-Path $env:LOCALAPPDATA "DarkWebThreatIntel"
        foreach ($name in @(
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
            "PLAYWRIGHT_BROWSERS_PATH",
            "DARKWEB_POSTGRESQL_DATA_DIRECTORY"
        )) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }

        $controlRoot = Join-Path $env:LOCALAPPDATA "DarkWebThreatIntel"
        $targetRoot = Join-Path $caseRoot "target"
        New-Item -ItemType Directory -Path $controlRoot -Force | Out-Null
        if ($caseName -in @("existing", "pending-migration")) {
            [IO.File]::WriteAllText((Join-Path $controlRoot "collector.db"), "first-run-migration")
        }
        if ($caseName -eq "pending-migration") {
            [IO.File]::WriteAllText((Join-Path $controlRoot "data-root-copy-manifest.json"), "{}")
        }

        & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
            -NoProfile -ExecutionPolicy Bypass -File $configurator `
            first-run -DataRoot $targetRoot -MinimumFreeGiB 1 -EnvironmentTarget Process
        if ($caseName -eq "pending-migration") {
            if ($LASTEXITCODE -eq 0) { throw "Pending migration was not blocked" }
            if (Test-Path -LiteralPath (Join-Path $targetRoot "collector.db") -PathType Leaf) {
                throw "Pending migration changed the target"
            }
            continue
        }
        if ($LASTEXITCODE -ne 0) { throw "$caseName first-run setup failed" }

        $config = Get-Content -LiteralPath (Join-Path $controlRoot "data-root.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([IO.Path]::GetFullPath([string]$config.data_root).TrimEnd("\") -ine [IO.Path]::GetFullPath($targetRoot).TrimEnd("\")) {
            throw "$caseName first-run setup selected the wrong target"
        }
        if ($caseName -eq "empty" -and $config.previous_data_root) {
            throw "Empty first-run setup unexpectedly used migration mode"
        }
        if ($caseName -eq "existing") {
            if (-not (Test-Path -LiteralPath (Join-Path $targetRoot "collector.db") -PathType Leaf)) {
                throw "Existing managed data was not copied"
            }
            if (-not $config.previous_data_root) {
                throw "Existing first-run setup did not retain a rollback source"
            }
        }
    }
}
finally {
    $resolvedSandbox = [IO.Path]::GetFullPath($sandbox)
    if ($resolvedSandbox.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $resolvedSandbox) -like "darkweb-first-run-*") {
        Remove-Item -LiteralPath $resolvedSandbox -Recurse -Force
    }
}

Write-Host "First-run setup tests passed."
exit 0
