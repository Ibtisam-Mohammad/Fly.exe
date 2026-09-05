# SPDX-License-Identifier: GPL-2.0-or-later
[CmdletBinding()]
param(
    [string]$DistroName = "FlyBrain",
    [string]$WslUser = "flybrain",
    [string]$FlysimPath = "/srv/flybrain-data/envs/production/bin/flysim",
    [string]$DatasetRoot = "/srv/flybrain-data",
    [string]$DatasetSpec = "/mnt/i/AI/fly_brain/configs/datasets/malecns-v1.0.json",
    [string]$LogPath = "I:\AI\fly_brain\artifacts\logs\contact-foundation-supervisor.log"
)

$ErrorActionPreference = "Stop"
$logDirectory = Split-Path -Parent $LogPath
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

function Write-FoundationLog {
    param([Parameter(Mandatory)][string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Message
    $line | Tee-Object -FilePath $LogPath -Append
}

function Invoke-Flysim {
    param([Parameter(Mandatory)][string[]]$FlysimArguments)
    $wslArguments = @(
        "-d", $DistroName,
        "-u", $WslUser,
        "--", "env", "PYTHONUNBUFFERED=1",
        $FlysimPath
    ) + $FlysimArguments
    $previousErrorAction = $ErrorActionPreference
    try {
        # Native stderr carries JSONL progress and must not become a terminating PowerShell error.
        $ErrorActionPreference = "Continue"
        & wsl.exe @wslArguments 2>&1 |
            Tee-Object -FilePath $LogPath -Append |
            Out-Null
        $nativeExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    return $nativeExitCode
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class FlyBrainFoundationPowerRequest
{
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint SetThreadExecutionState(uint flags);

    public static bool PreventSystemSleep()
    {
        return SetThreadExecutionState(0x80000001u) != 0;
    }

    public static void RestoreDefaults()
    {
        SetThreadExecutionState(0x80000000u);
    }
}
"@

$mutex = [System.Threading.Mutex]::new($false, "Local\MaleCNSContactFoundationSupervisor")
if (-not $mutex.WaitOne(0)) {
    Write-FoundationLog "Another contact-foundation supervisor is already running; exiting."
    exit 3
}

$pidPath = Join-Path $logDirectory "contact-foundation-supervisor.pid"
$completionPath = Join-Path $logDirectory "contact-foundation-supervisor.complete"
$failurePath = Join-Path $logDirectory "contact-foundation-supervisor.failed.json"
Set-Content -Path $pidPath -Value $PID -Encoding ascii
Remove-Item -LiteralPath $completionPath -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $failurePath -ErrorAction SilentlyContinue

try {
    if (-not [FlyBrainFoundationPowerRequest]::PreventSystemSleep()) {
        Write-FoundationLog "WARNING: Windows rejected the temporary sleep-prevention request."
    }
    Write-FoundationLog "Starting resumable bounded-memory contact normalization."
    foreach ($artifactId in @(
        "connectome-weights", "syn-points", "syn-partners", "tbar-neurotransmitters"
    )) {
        do {
            $importExit = Invoke-Flysim @(
                "data", "import-contacts", "--resume", "--artifact", $artifactId,
                "--memory-limit-gb", "3", "--threads", "2", "--minimum-free-gb", "80",
                "--max-new-shards-per-process", "24",
                "--root", $DatasetRoot, "--spec", $DatasetSpec
            )
            if ($importExit -eq 75) {
                Write-FoundationLog (
                    "Verified $artifactId checkpoint; recycling the WSL worker."
                )
            }
        } while ($importExit -eq 75)
        if ($importExit -ne 0) {
            throw "Contact import exited for $artifactId with code $importExit."
        }
    }

    Write-FoundationLog "Contact derivatives complete; starting strict structural audit."
    $auditExit = Invoke-Flysim @(
        "data", "audit-contacts",
        "--strict",
        "--memory-limit-gb", "3",
        "--threads", "1",
        "--root", $DatasetRoot
    )
    if ($auditExit -ne 0) {
        throw "Strict contact audit exited with code $auditExit. No validation tier was awarded."
    }

    Write-FoundationLog "Contact audit passed; starting body-universe sensitivity audit."
    $universeExit = Invoke-Flysim @(
        "data", "audit-body-universes",
        "--root", $DatasetRoot
    )
    if ($universeExit -ne 0) {
        throw "Body-universe sensitivity audit exited with code $universeExit."
    }

    $completedAt = Get-Date -Format "o"
    Set-Content -Path $completionPath -Value $completedAt -Encoding ascii
    Write-FoundationLog "Contact, structural, and body-universe foundation audits completed."
}
catch {
    $failure = [ordered]@{
        schema_version = "1.0"
        observed_at = (Get-Date -Format "o")
        retryable = $false
        error = $_.Exception.Message
    }
    $failure | ConvertTo-Json | Set-Content -Path $failurePath -Encoding utf8
    Write-FoundationLog "FAILED: $($_.Exception.Message)"
    exit 2
}
finally {
    [FlyBrainFoundationPowerRequest]::RestoreDefaults()
    Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
