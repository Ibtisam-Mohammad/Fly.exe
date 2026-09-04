# SPDX-License-Identifier: GPL-2.0-or-later
[CmdletBinding()]
param(
    [string]$DistributionName = "FlyBrain",
    [string]$InstallPath = "D:\WSL\FlyBrain",
    [string]$VhdSize = "180GB"
)

$ErrorActionPreference = "Stop"
$resolvedParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $InstallPath))
if (-not $resolvedParent.StartsWith("D:\WSL", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Install path must remain under D:\WSL"
}
$freeBytes = (Get-PSDrive -Name D).Free
if ($freeBytes -lt 40GB) {
    throw "D: must retain at least 40 GB free"
}
$installed = wsl --list --quiet | ForEach-Object { $_.Trim([char]0).Trim() }
if ($installed -notcontains $DistributionName) {
    wsl --install Ubuntu-24.04 --name $DistributionName --location $InstallPath --version 2 --vhd-size $VhdSize --no-launch --web-download
}
# The VHD is dynamically allocated and capped by --vhd-size. Do not force WSL's
# unsafe sparse-reclamation flag on hosts where Microsoft has disabled it.
wsl -d $DistributionName -u root -- bash -lc "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential ca-certificates curl ffmpeg git libegl1 libffi-dev libgl1 libglfw3 libosmesa6 nvidia-cuda-toolkit pkg-config python3.12 python3.12-dev python3.12-venv"
wsl -d $DistributionName -u root -- bash -lc "id -u flybrain >/dev/null 2>&1 || useradd --create-home --shell /bin/bash flybrain; install -d -o flybrain -g flybrain /srv/flybrain-data"
wsl --manage $DistributionName --set-default-user flybrain
Write-Output "WSL environment ready: $DistributionName; data root: /srv/flybrain-data"
