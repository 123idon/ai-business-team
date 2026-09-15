$ErrorActionPreference = 'Stop'
$officeRoot = $PSScriptRoot
$pythonPath = (& python -c 'import sys; print(sys.executable)').Trim()
$officeScript = Join-Path $officeRoot 'office.py'
$ready = $false
try {
    $response = Invoke-WebRequest 'http://127.0.0.1:8765/' -TimeoutSec 2
    $ready = $response.Content -match 'LEE · LOCAL AI OFFICE'
} catch { }
if (-not $ready) {
    Start-Process -FilePath $pythonPath -ArgumentList @(('"' + $officeScript + '"'), 'serve') -WorkingDirectory $officeRoot -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        Start-Sleep -Milliseconds 200
        try {
            $response = Invoke-WebRequest 'http://127.0.0.1:8765/' -TimeoutSec 1
            if ($response.Content -match 'LEE · LOCAL AI OFFICE') { $ready = $true; break }
        } catch { }
    }
}
if (-not $ready) { throw 'AI Office dashboard did not start. Check port 8765.' }
Start-Process 'http://127.0.0.1:8765/'
