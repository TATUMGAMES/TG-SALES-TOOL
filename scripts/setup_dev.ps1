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
    Create the development virtual environment with hash-verified dependencies.
.DESCRIPTION
    Creates .venv in the repository root using Python 3.13 (64-bit), installs the
    exact versions pinned in requirements-dev.lock, then installs tg_sales itself
    in editable mode. Safe to re-run.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host 'Creating .venv with Python 3.13...'
    & py -3.13 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 (64-bit) is required. Install it from python.org and re-run.' }
}

& $venvPython -m pip install --disable-pip-version-check --require-hashes -r requirements-dev.lock
if ($LASTEXITCODE -ne 0) { throw 'Failed to install locked dependencies.' }

& $venvPython -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e .
if ($LASTEXITCODE -ne 0) { throw 'Failed to install tg_sales in editable mode.' }

Write-Host 'Development environment ready: .venv'
