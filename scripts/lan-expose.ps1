#Requires -Version 5.1
<#
.SYNOPSIS
  Expose smart-pdf2md (localhost:8000) to the LAN via netsh portproxy + firewall.

.DESCRIPTION
  Auto-detects the Wi-Fi IPv4 address, creates a portproxy
  <Wi-Fi-IP>:8000 -> 127.0.0.1:8000, and an inbound firewall rule
  'smartmd LAN 8000' scoped to RemoteAddress 10.15.188.0/23.

  Must be run as Administrator. Does not attempt self-elevation.
#>
[CmdletBinding()]
param(
    [string]$InterfaceAlias = 'Wi-Fi',
    [int]$ListenPort = 8000,
    [string]$ConnectAddress = '127.0.0.1',
    [int]$ConnectPort = 8000,
    [string]$RemoteSubnet = '10.15.188.0/23',
    [string]$FirewallRuleName = 'smartmd LAN 8000'
)

$ErrorActionPreference = 'Stop'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-WifiIPv4 {
    param([string]$Alias)

    $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias $Alias -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -and $_.IPAddress -notlike '169.254.*' } |
        Sort-Object -Property PrefixOrigin)

    if (-not $addresses -or $addresses.Count -eq 0) {
        throw "No IPv4 address found on interface '$Alias'. Check Wi-Fi connection or pass -InterfaceAlias."
    }

    return $addresses[0].IPAddress
}

if (-not (Test-IsAdministrator)) {
    Write-Error "This script must be run as Administrator (elevated PowerShell). Right-click PowerShell -> Run as administrator, then re-run."
    exit 1
}

Write-Host "==> smartmd LAN expose" -ForegroundColor Cyan

# IP Helper is required for portproxy
$iphlp = Get-Service -Name 'iphlpsvc' -ErrorAction SilentlyContinue
if (-not $iphlp) {
    Write-Error "Service 'iphlpsvc' (IP Helper) not found. Cannot create portproxy."
    exit 1
}
if ($iphlp.Status -ne 'Running') {
    Write-Host "IP Helper (iphlpsvc) is $($iphlp.Status). Attempting to start..." -ForegroundColor Yellow
    try {
        Start-Service -Name 'iphlpsvc'
        Start-Sleep -Seconds 1
        $iphlp.Refresh()
    } catch {
        Write-Error "Failed to start IP Helper (iphlpsvc): $_. Start it manually: Start-Service iphlpsvc"
        exit 1
    }
    if ($iphlp.Status -ne 'Running') {
        Write-Error "IP Helper (iphlpsvc) is still not Running (status: $($iphlp.Status))."
        exit 1
    }
    Write-Host "IP Helper started." -ForegroundColor Green
} else {
    Write-Host "IP Helper (iphlpsvc): Running" -ForegroundColor Green
}

try {
    $ip = Get-WifiIPv4 -Alias $InterfaceAlias
} catch {
    Write-Error $_
    exit 1
}
Write-Host "Detected $InterfaceAlias IPv4: $ip" -ForegroundColor Green

# Refresh portproxy for this listen address/port
Write-Host "Configuring portproxy $ip`:$ListenPort -> ${ConnectAddress}:$ConnectPort ..."
$null = netsh interface portproxy delete v4tov4 listenport=$ListenPort listenaddress=$ip 2>$null
$addOut = netsh interface portproxy add v4tov4 listenaddress=$ip listenport=$ListenPort connectaddress=$ConnectAddress connectport=$ConnectPort 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "netsh portproxy add failed (exit $LASTEXITCODE): $addOut"
    exit 1
}

# Firewall rule: allow inbound TCP only from LAN subnet
$existing = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Updating firewall rule '$FirewallRuleName' ..."
    Remove-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction Stop
}

New-NetFirewallRule `
    -DisplayName $FirewallRuleName `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $ListenPort `
    -Action Allow `
    -Profile Any `
    -RemoteAddress $RemoteSubnet `
    -ErrorAction Stop | Out-Null

Write-Host ""
Write-Host "LAN URL:  http://${ip}:${ListenPort}" -ForegroundColor Green
Write-Host "Health:   http://${ip}:${ListenPort}/healthz" -ForegroundColor Green
Write-Host "Remote clients must be in $RemoteSubnet" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Verify locally:" -ForegroundColor Cyan
Write-Host "  netsh interface portproxy show v4tov4"
Write-Host "  Get-NetFirewallRule -DisplayName '$FirewallRuleName'"
Write-Host ""
Write-Host "Done. Open the LAN URL from another device on the same network." -ForegroundColor Green
exit 0
