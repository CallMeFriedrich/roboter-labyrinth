<#
  Roboter-Labyrinth – einmalige Einrichtung unter Windows.

    powershell -ExecutionPolicy Bypass -File setup_windows.ps1

  1. Python-Umgebung (.venv) anlegen und Pakete installieren (braucht Internet).
  2. Firewall-Regel für Port 8000 im privaten Netz (nur als Administrator).
  3. Hinweise zu Netzwerk, Hotspot und Energiesparen.
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$Port = 8000

Write-Host ""
Write-Host "== 1. Python-Umgebung" -ForegroundColor Cyan
$python = $null
foreach ($candidate in @("py -3.12", "python")) {
    try {
        $version = Invoke-Expression "$candidate --version" 2>$null
        if ($version -match "Python 3\.1[2-9]") { $python = $candidate; break }
    } catch { }
}
if (-not $python) {
    Write-Host "Python 3.12 wurde nicht gefunden. Bitte von https://www.python.org installieren" -ForegroundColor Red
    Write-Host "(Haken bei 'Add python.exe to PATH' setzen) und das Skript erneut starten."
    exit 1
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Lege .venv an ($python) ..."
    Invoke-Expression "$python -m venv .venv"
}
Write-Host "Installiere Pakete aus requirements.txt ..."
& ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "Die Installation ist fehlgeschlagen." -ForegroundColor Red; exit 1 }
Write-Host "Python-Umgebung ist bereit." -ForegroundColor Green

Write-Host ""
Write-Host "== 2. Firewall (Port $Port, privates Netz)" -ForegroundColor Cyan
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$ruleName = "Roboter-Labyrinth (Port $Port)"
if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Write-Host "Die Regel '$ruleName' gibt es schon." -ForegroundColor Green
} elseif ($isAdmin) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort $Port -Profile Private | Out-Null
    Write-Host "Regel '$ruleName' angelegt." -ForegroundColor Green
} else {
    Write-Host "Nicht als Administrator gestartet: Die Firewall-Regel wurde NICHT angelegt." -ForegroundColor Yellow
    Write-Host "Das Tablet erreicht den Laptop erst mit dieser Regel. Entweder dieses Skript in einer"
    Write-Host "PowerShell 'Als Administrator' erneut starten oder dort diesen Befehl ausführen:"
    Write-Host ""
    Write-Host "  New-NetFirewallRule -DisplayName '$ruleName' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Private"
    Write-Host ""
    Write-Host "Zum Testen nur auf diesem PC (localhost) ist die Regel nicht nötig."
}

Write-Host ""
Write-Host "== 3. Von Hand einrichten" -ForegroundColor Cyan
Write-Host "Ethernet zum Roboter : feste IP 192.168.0.100, Maske 255.255.255.0 (Roboter: 192.168.0.30)"
Write-Host "Mobiler Hotspot      : Einstellungen > Netzwerk und Internet > Mobiler Hotspot > Ein"
Write-Host "                       Der Laptop hat dort 192.168.137.1; das Hotspot-Netz muss 'Privat' sein."
Write-Host "Tablet               : http://192.168.137.1:$Port/admin  ->  Teilen > Zum Home-Bildschirm"
Write-Host "Besucher-Monitor     : als zweiten Bildschirm rechts vom Laptop 'erweitern' (Position in start.bat)"
Write-Host "Vor der Veranstaltung: Energiesparen und Bildschirmschoner aus, 'Nicht stören' ein, Updates pausieren"
Write-Host "Admin-PIN ändern     : .venv\Scripts\python tools\set_pin.py"
Write-Host ""
Write-Host "Fertig. Start mit start.bat" -ForegroundColor Green
