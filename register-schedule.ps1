$ErrorActionPreference = 'Stop'
$officeRoot = $PSScriptRoot
$pythonPath = (& python -c 'import sys; print(sys.executable)').Trim()
$officeScript = Join-Path $officeRoot 'office.py'
$officeUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $officeUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
foreach ($entry in @(@{Name='AI-Office-Morning';Time='09:00';Kind='plan'},@{Name='AI-Office-Close';Time='18:00';Kind='close'})) {
    $name = $entry.Name
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing -and $existing.Description -notlike 'AI Office v1.1*') { throw "Existing unrelated task: $name" }
    $tail = if ($entry.Kind -eq 'plan') { 'daily' } else { 'report --kind close' }
    $action = New-ScheduledTaskAction -Execute $pythonPath -Argument ('"' + $officeScript + '" ' + $tail) -WorkingDirectory $officeRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $entry.Time
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'AI Office v1.1 two-office team; morning up to four tasks; evening local report; subscription only' -Force | Select-Object TaskName,State
}
