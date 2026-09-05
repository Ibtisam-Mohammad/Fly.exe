# SPDX-License-Identifier: GPL-2.0-or-later
[CmdletBinding()]
param(
    [string]$DistroName = "FlyBrain",
    [string]$WslUser = "flybrain",
    [string]$FlysimPath = "/srv/flybrain-data/envs/production/bin/flysim",
    [string]$DatasetRoot = "/srv/flybrain-data",
    [string]$DatasetSpec = "/mnt/i/AI/fly_brain/configs/datasets/malecns-v1.0.json",
    [string]$LogPath = "I:\AI\fly_brain\artifacts\logs\full-dataset-supervisor.log",
    [int]$RetrySeconds = 30
)

$ErrorActionPreference = "Stop"
$logDirectory = Split-Path -Parent $LogPath
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

function Write-SupervisorLog {
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
    & wsl.exe @wslArguments 2>&1 |
        Tee-Object -FilePath $LogPath -Append |
        Out-Null
    $exitCode = $LASTEXITCODE
    return $exitCode
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class FlyBrainPowerRequest
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

$mutex = [System.Threading.Mutex]::new($false, "Local\MaleCNSFullDatasetSupervisor")
if (-not $mutex.WaitOne(0)) {
    Write-SupervisorLog "Another full-dataset supervisor is already running; exiting."
    exit 3
}

$pidPath = Join-Path $logDirectory "full-dataset-supervisor.pid"
$completionPath = Join-Path $logDirectory "full-dataset-supervisor.complete"
Set-Content -Path $pidPath -Value $PID -Encoding ascii
Remove-Item -LiteralPath $completionPath -ErrorAction SilentlyContinue

try {
    if (-not [FlyBrainPowerRequest]::PreventSystemSleep()) {
        Write-SupervisorLog "WARNING: Windows rejected the temporary sleep-prevention request."
    }
    Write-SupervisorLog "Supervisor started as PID $PID; WSL remains host-attached."

    while ($true) {
        Write-SupervisorLog "Checking whether the complete MaleCNS full profile is valid."
        $validateExit = Invoke-Flysim @(
            "data", "validate",
            "--profile", "full",
            "--root", $DatasetRoot,
            "--spec", $DatasetSpec
        )
        if ($validateExit -eq 0) {
            $completedAt = Get-Date -Format "o"
            Set-Content -Path $completionPath -Value $completedAt -Encoding ascii
            Write-SupervisorLog "Full profile is complete and checksum-valid."
            exit 0
        }

        Write-SupervisorLog "Validation exit $validateExit; starting or resuming full sync."
        $syncExit = Invoke-Flysim @(
            "data", "sync",
            "--profile", "full",
            "--root", $DatasetRoot,
            "--spec", $DatasetSpec
        )
        Write-SupervisorLog "Sync exited with code $syncExit; completion will be revalidated."

        $validateExit = Invoke-Flysim @(
            "data", "validate",
            "--profile", "full",
            "--root", $DatasetRoot,
            "--spec", $DatasetSpec
        )
        if ($validateExit -eq 0) {
            $completedAt = Get-Date -Format "o"
            Set-Content -Path $completionPath -Value $completedAt -Encoding ascii
            Write-SupervisorLog "Full profile is complete and checksum-valid."
            exit 0
        }

        Write-SupervisorLog "Full profile is still incomplete; retrying in $RetrySeconds seconds."
        Start-Sleep -Seconds $RetrySeconds
    }
}
finally {
    [FlyBrainPowerRequest]::RestoreDefaults()
    Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
