# SPDX-License-Identifier: GPL-2.0-or-later
[CmdletBinding()]
param(
    [string]$DistroName = "FlyBrain",
    [string]$WslUser = "flybrain",
    [string]$FlysimPath = "/srv/flybrain-data/envs/production/bin/flysim",
    [string]$DatasetRoot = "/srv/flybrain-data",
    [string]$DatasetSpec = "/mnt/i/AI/fly_brain/configs/datasets/malecns-v1.0.json",
    [string]$FoundationMarker = "I:\AI\fly_brain\artifacts\logs\contact-foundation-supervisor.complete",
    [string]$FoundationFailure = "I:\AI\fly_brain\artifacts\logs\contact-foundation-supervisor.failed.json",
    [string]$LogPath = "I:\AI\fly_brain\artifacts\logs\contact-rebuild-supervisor.log"
)

$ErrorActionPreference = "Stop"
$logDirectory = Split-Path -Parent $LogPath
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

function Write-RebuildLog {
    param([Parameter(Mandatory)][string]$Message)
    "{0} {1}" -f (Get-Date -Format "o"), $Message |
        Tee-Object -FilePath $LogPath -Append
}

function Invoke-Flysim {
    param([Parameter(Mandatory)][string[]]$FlysimArguments)
    $arguments = @(
        "-d", $DistroName, "-u", $WslUser, "--",
        "env", "PYTHONUNBUFFERED=1", $FlysimPath
    ) + $FlysimArguments
    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & wsl.exe @arguments 2>&1 | Tee-Object -FilePath $LogPath -Append | Out-Null
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
}

function Invoke-RecycledImport {
    param(
        [Parameter(Mandatory)][string]$OutputRoot,
        [Parameter(Mandatory)][int]$RowGroupRows
    )
    do {
        $exitCode = Invoke-Flysim @(
            "data", "import-contacts", "--resume",
            "--memory-limit-gb", "3", "--threads", "2", "--minimum-free-gb", "80",
            "--max-new-shards-per-process", "48",
            "--row-group-rows", "$RowGroupRows", "--shard-rows", "1048576",
            "--output-root", $OutputRoot,
            "--root", $DatasetRoot, "--spec", $DatasetSpec
        )
        if ($exitCode -eq 75) {
            Write-RebuildLog "Verified checkpoint reached for $OutputRoot; recycling worker."
        }
    } while ($exitCode -eq 75)
    if ($exitCode -ne 0) {
        throw "Contact rebuild failed for $OutputRoot with exit code $exitCode."
    }
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class FlyBrainRebuildPowerRequest
{
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint SetThreadExecutionState(uint flags);
    public static bool PreventSystemSleep() { return SetThreadExecutionState(0x80000001u) != 0; }
    public static void RestoreDefaults() { SetThreadExecutionState(0x80000000u); }
}
"@

$mutex = [System.Threading.Mutex]::new($false, "Local\MaleCNSContactRebuildSupervisor")
if (-not $mutex.WaitOne(0)) {
    Write-RebuildLog "Another contact rebuild supervisor is active; exiting."
    exit 3
}

$pidPath = Join-Path $logDirectory "contact-rebuild-supervisor.pid"
$completePath = Join-Path $logDirectory "contact-rebuild-supervisor.complete"
$failedPath = Join-Path $logDirectory "contact-rebuild-supervisor.failed.json"
Set-Content -LiteralPath $pidPath -Value $PID -Encoding ascii
Remove-Item -LiteralPath $completePath -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $failedPath -ErrorAction SilentlyContinue

try {
    [FlyBrainRebuildPowerRequest]::PreventSystemSleep() | Out-Null
    Write-RebuildLog "Waiting for the canonical normalization and strict audit completion marker."
    while (-not (Test-Path -LiteralPath $FoundationMarker)) {
        if (Test-Path -LiteralPath $FoundationFailure) {
            throw "Canonical foundation job failed; rebuild will not start."
        }
        Start-Sleep -Seconds 30
    }

    $canonical = "$DatasetRoot/derived/male-cns-v1.0/contacts-rebuild-262144"
    $alternate = "$DatasetRoot/derived/male-cns-v1.0/contacts-rebuild-131072"
    Write-RebuildLog "Starting clean 262144-row-group rebuild."
    Invoke-RecycledImport -OutputRoot $canonical -RowGroupRows 262144
    Write-RebuildLog "Starting independent 131072-row-group rebuild."
    Invoke-RecycledImport -OutputRoot $alternate -RowGroupRows 131072

    $evidenceRoot = "$DatasetRoot/evidence/male-cns-v1.0"
    $originalCompare = Invoke-Flysim @(
        "data", "verify-contact-rebuild",
        "--left", "$DatasetRoot/derived/male-cns-v1.0/contacts",
        "--right", $canonical,
        "--output", "$evidenceRoot/canonical-contact-rebuild.json"
    )
    if ($originalCompare -ne 0) {
        throw "Original-to-clean canonical logical comparison failed with $originalCompare."
    }
    $batchCompare = Invoke-Flysim @(
        "data", "verify-contact-rebuild",
        "--left", $canonical, "--right", $alternate,
        "--output", "$evidenceRoot/contact-batch-size-reproducibility.json"
    )
    if ($batchCompare -ne 0) {
        throw "Batch-size reproducibility comparison failed with $batchCompare."
    }
    Set-Content -LiteralPath $completePath -Value (Get-Date -Format "o") -Encoding ascii
    Write-RebuildLog "Both clean rebuilds and logical comparisons passed."
}
catch {
    [ordered]@{
        schema_version = "1.0"
        observed_at = (Get-Date -Format "o")
        retryable = $false
        error = $_.Exception.Message
    } | ConvertTo-Json | Set-Content -LiteralPath $failedPath -Encoding utf8
    Write-RebuildLog "FAILED: $($_.Exception.Message)"
    exit 2
}
finally {
    [FlyBrainRebuildPowerRequest]::RestoreDefaults()
    Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
