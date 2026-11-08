<#
.SYNOPSIS
    Run all local quality gates: backend formatting, lint, types and tests;
    API type sync; web type check, unit tests and build; optionally browser tests.
.DESCRIPTION
    Stops at the first failing step and exits non-zero. Pass -Fix to apply
    automatic formatting and lint fixes before checking, -E2E to also run the
    Playwright browser tests, and -Audit to check dependencies for known
    vulnerabilities (needs internet).
#>
[CmdletBinding()]
param([switch]$Fix, [switch]$E2E, [switch]$Audit)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { throw 'Run scripts\setup_dev.ps1 first.' }

function Invoke-Step([string]$Name, [string[]]$Arguments) {
    Write-Host "==> $Name"
    & $venvPython @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if ($Fix) {
    Invoke-Step 'ruff format (fix)' @('-m', 'ruff', 'format', 'src', 'tests')
    Invoke-Step 'ruff check (fix)' @('-m', 'ruff', 'check', '--fix', 'src', 'tests')
}

function Invoke-Npm([string]$Name, [string[]]$Arguments) {
    Write-Host "==> $Name"
    Push-Location (Join-Path $root 'web')
    try {
        & npm.cmd @Arguments
        if ($LASTEXITCODE -ne 0) {
            Write-Host "FAILED: $Name" -ForegroundColor Red
            exit $LASTEXITCODE
        }
    } finally { Pop-Location }
}

Invoke-Step 'ruff format --check' @('-m', 'ruff', 'format', '--check', 'src', 'tests', 'scripts')
Invoke-Step 'ruff check' @('-m', 'ruff', 'check', 'src', 'tests', 'scripts')
Invoke-Step 'mypy' @('-m', 'mypy')
Invoke-Step 'API types up to date' @('scripts\generate_api_types.py', '--check')
Invoke-Step 'pytest' @('-m', 'pytest')
Invoke-Npm 'web: type check' @('run', 'typecheck')
Invoke-Npm 'web: unit tests' @('test')
Invoke-Npm 'web: build' @('run', 'build')
if ($E2E) { Invoke-Npm 'web: browser tests' @('run', 'e2e') }
if ($Audit) {
    Invoke-Step 'pip-audit' @('-m', 'pip_audit', '--strict', '-r', 'requirements.lock')
    Invoke-Npm 'npm audit' @('audit', '--audit-level=moderate')
}

Write-Host 'All checks passed.' -ForegroundColor Green
