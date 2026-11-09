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
    Build the Windows release folder and ZIP: tg_sales.exe + PostgreSQL runtime + web app.
.DESCRIPTION
    Output: dist\tg_sales_windows_x64_v<version>\ and dist\tg_sales_windows_x64_v<version>.zip
    plus dist\SHA256SUMS.txt. Requires the development setup (setup.bat), which provides
    the Python environment, runtime\postgresql and Node.js.
#>
[CmdletBinding()]
param([switch]$SkipWeb)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Run setup.bat first.' }
if (-not (Test-Path 'runtime\postgresql\bin\pg_ctl.exe')) { & $python scripts\setup_postgres.py; if ($LASTEXITCODE) { throw 'PostgreSQL runtime missing.' } }

$version = & $python -c "import tg_sales; print(tg_sales.__version__)"
$name = "tg_sales_windows_x64_v$version"
Write-Host "Building $name"

if (-not $SkipWeb) {
    Push-Location web
    & npm.cmd ci --no-fund --no-audit; if ($LASTEXITCODE) { throw 'npm ci failed' }
    & npm.cmd run build; if ($LASTEXITCODE) { throw 'web build failed' }
    Pop-Location
}

# Icon and Windows version information.
New-Item -ItemType Directory -Force build | Out-Null
& $python -c @"
from PIL import Image
Image.open('web/public/icons/icon-512.png').save('build/tg_sales.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
"@
$parts = ($version.Split('.') + @('0','0','0'))[0..3] -join ', '
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts), prodvers=($parts)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Tatum Games'),
    StringStruct('FileDescription', 'TG Sales CRM'),
    StringStruct('FileVersion', '$version'),
    StringStruct('ProductName', 'TG Sales CRM'),
    StringStruct('ProductVersion', '$version'),
    StringStruct('OriginalFilename', 'tg_sales.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -Encoding utf8 build\version_info.txt

& $python -m PyInstaller --noconfirm --clean --distpath build\pyinstaller --workpath build\work tg_sales.spec
if ($LASTEXITCODE) { throw 'PyInstaller failed' }

$out = Join-Path 'dist' $name
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force $out | Out-Null
Copy-Item -Recurse 'build\pyinstaller\tg_sales\*' $out
New-Item -ItemType Directory -Force "$out\runtime" | Out-Null
Copy-Item -Recurse 'runtime\postgresql' "$out\runtime\postgresql"
Copy-Item -Recurse 'web\dist' "$out\web"
Copy-Item launch.bat, stop.bat, LICENSE, NOTICE, TRADEMARKS.md $out
Copy-Item 'docs\INSTALL_WINDOWS.txt' "$out\README.txt"

$zip = "dist\$name.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$out\*" -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $name.zip" | Set-Content -Encoding ascii dist\SHA256SUMS.txt
Write-Host "Built $zip ($([math]::Round((Get-Item $zip).Length / 1MB)) MB), SHA256 $hash"
