# Run only in an Administrator PowerShell. This script never restarts the PC.
$ErrorActionPreference = 'Stop'
$isAdmin = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw 'Administrator PowerShell is required.' }
wsl.exe --install --no-distribution
Write-Host 'If Windows requests restart, save your work and restart manually. Then run: wsl --install -d Ubuntu --no-launch'
