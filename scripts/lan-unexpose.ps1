#Requires -Version 5.1
<#
.SYNOPSIS
  Remove smart-pdf2md LAN portproxy and firewall rule.

.DESCRIPTION
  Deletes the Wi-Fi IPv4 portproxy for port 8000 and removes the
  firewall rule 'smartmd LAN 8000'. Safe to re-run if rules are already gone.

  Must be run as Administrator. Does not attempt self-elevation.
#>
[CmdletBinding()]
param(
    [string]$InterfaceAlias = 'Wi-Fi',
    [int]$ListenPort = 8000,
    [string]$FirewallRuleName = 'smartmd LAN 8000',
    [switch]$AllPortProxiesOnPort
)

$ErrorActionPreference = 'Stop'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    Write-Error "This script must be run as Administrator (elevated PowerShell). Right-click PowerShell -> Run as administrator, then re-run."
    exit 1
}

Write-Host "==> smartmd LAN unexpose" -ForegroundColor Cyan

$removedProxy = $false
$removedFw = $false

# Remove portproxy for current Wi-Fi IP (and optionally any listen address on the port)
$ip = $null
try {
    $addr = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias $InterfaceAlias -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1
    if ($addr) { $ip = $addr.IPAddress }
} catch {
    # Interface may be down; continue with show/delete best-effort
}

if ($ip) {
    Write-Host "Wi-Fi IPv4: $ip — removing portproxy listen $ip`:$ListenPort ..."
    $null = netsh interface portproxy delete v4tov4 listenport=$ListenPort listenaddress=$ip 2>$null
    if ($LASTEXITCODE -eq 0) { $removedProxy = $true }
} else {
    Write-Host "Could not detect IPv4 on '$InterfaceAlias' (interface down or renamed)." -ForegroundColor Yellow
}

if ($AllPortProxiesOnPort) {
    # Parse current portproxy table and delete any entry listening on ListenPort
    $show = netsh interface portproxy show v4tov4 2>$null
    foreach ($line in $show) {
        if ($line -match '^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+(\d+)\s+') {
            $listenAddr = $Matches[1]
            $port = [int]$Matches[2]
            if ($port -eq $ListenPort) {
                Write-Host "Removing portproxy $listenAddr`:$port ..."
                $null = netsh interface portproxy delete v4tov4 listenport=$port listenaddress=$listenAddr 2>$null
                if ($LASTEXITCODE -eq 0) { $removedProxy = $true }
            }
        }
    }
}

# Firewall rule
$existing = @(Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue)
if ($existing.Count -gt 0) {
    Write-Host "Removing firewall rule '$FirewallRuleName' ..."
    Remove-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction Stop
    $removedFw = $true
} else {
    Write-Host "Firewall rule '$FirewallRuleName' not found (already clean)." -ForegroundColor DarkGray
}

Write-Host ""
if ($removedProxy -or $removedFw) {
    Write-Host "Cleaned up:" -ForegroundColor Green
    if ($removedProxy) { Write-Host "  - portproxy on port $ListenPort" }
    if ($removedFw) { Write-Host "  - firewall rule '$FirewallRuleName'" }
} else {
    Write-Host "Nothing to remove (or portproxy delete was no-op). Current portproxy table:" -ForegroundColor Yellow
    netsh interface portproxy show v4tov4
}

Write-Host ""
Write-Host "Done. LAN access to smartmd on port $ListenPort is closed." -ForegroundColor Green
exit 0
