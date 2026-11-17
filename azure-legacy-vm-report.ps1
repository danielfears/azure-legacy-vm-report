#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Native Windows PowerShell launcher for azure-legacy-vm-report.
.DESCRIPTION
  Runs azure-legacy-vm-report with UTF-8 output enabled, or performs a device-code
  Azure CLI login via `.\azure-legacy-vm-report.ps1 login [tenant-id]`.
#>
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($args.Count -ge 1 -and $args[0] -eq 'login') {
    if ($args.Count -eq 1) {
        Start-Process 'https://login.microsoft.com/device' -ErrorAction SilentlyContinue | Out-Null
        & az login --scope 'https://management.azure.com//.default' --use-device-code --allow-no-subscriptions
        exit $LASTEXITCODE
    }
    $tenant = [string]$args[1]
    if ($args.Count -gt 2 -or $tenant -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]*$') {
        [Console]::Error.WriteLine('usage: azure-legacy-vm-report.ps1 login [tenant-id-or-domain]')
        exit 2
    }
    Start-Process 'https://login.microsoft.com/device' -ErrorAction SilentlyContinue | Out-Null
    & az login --tenant $tenant --scope 'https://management.azure.com//.default' --use-device-code --allow-no-subscriptions
    exit $LASTEXITCODE
}

$prevUtf8 = $env:PYTHONUTF8
$prevNoBytecode = $env:PYTHONDONTWRITEBYTECODE
$prevPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONUTF8 = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONPATH = if ($prevPythonPath) { "$here$([IO.Path]::PathSeparator)$prevPythonPath" } else { $here }
    & python -m azure_legacy_vm_report @args
    exit $LASTEXITCODE
} finally {
    $env:PYTHONUTF8 = $prevUtf8
    $env:PYTHONDONTWRITEBYTECODE = $prevNoBytecode
    $env:PYTHONPATH = $prevPythonPath
}
