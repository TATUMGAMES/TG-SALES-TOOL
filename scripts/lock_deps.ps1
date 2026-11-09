# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

<#
.SYNOPSIS
    Regenerate the hash-pinned dependency lock files from pyproject.toml.
.DESCRIPTION
    Writes requirements.lock (runtime) and requirements-dev.lock (runtime + dev
    tools). Run from the development environment on Windows x64 with Python 3.13,
    which is the only supported build target. Pass -Upgrade to move every pin to
    the newest version allowed by pyproject.toml.

    As a supply-chain safeguard, packages uploaded within the last -CooldownDays
    days (default 14) are not selected.
#>
[CmdletBinding()]
param([switch]$Upgrade, [int]$CooldownDays = 14)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { throw 'Run scripts\setup_dev.ps1 first.' }

$cutoff = (Get-Date).ToUniversalTime().AddDays(-$CooldownDays).ToString('yyyy-MM-dd')
$common = @(
    '--quiet', '--generate-hashes', '--allow-unsafe', '--strip-extras', '--no-emit-index-url',
    "--pip-args=--uploaded-prior-to=$cutoff"
)
if ($Upgrade) { $common += '--upgrade' }

& $venvPython -m piptools compile @common --output-file requirements.lock pyproject.toml
if ($LASTEXITCODE -ne 0) { throw 'Failed to compile requirements.lock.' }

& $venvPython -m piptools compile @common --extra dev --output-file requirements-dev.lock pyproject.toml
if ($LASTEXITCODE -ne 0) { throw 'Failed to compile requirements-dev.lock.' }

Write-Host 'Updated requirements.lock and requirements-dev.lock'
