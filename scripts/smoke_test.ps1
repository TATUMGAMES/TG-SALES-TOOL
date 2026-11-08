<#
.SYNOPSIS
    Start a built release folder with a temporary data folder, check that the
    app and its database work, then stop it. Used after scripts\build_windows.ps1.
#>
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Folder, [int]$Port = 8765)

$ErrorActionPreference = 'Stop'
$data = Join-Path ([IO.Path]::GetTempPath()) ("tg_sales_smoke_" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$exe = Join-Path $Folder 'tg_sales.exe'
$proc = Start-Process -FilePath $exe -ArgumentList @('start', '--data-dir', $data, '--no-browser', '--port', $Port) -PassThru -WindowStyle Hidden
try {
    $ok = $false
    for ($i = 0; $i -lt 120 -and -not $ok; $i++) {
        Start-Sleep -Seconds 1
        try { $ok = (Invoke-RestMethod "http://127.0.0.1:$Port/api/health").status -eq 'ok' } catch { }
    }
    if (-not $ok) { throw 'tg_sales did not become healthy' }
    $page = Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing
    if ($page.Content -notmatch 'TG Sales CRM') { throw 'web app not served' }
    $headers = @{ 'X-TG-Sales' = '1' }
    $body = '{"organization":{"name":"Smoke Test Studio"}}'
    Invoke-RestMethod -Method Post "http://127.0.0.1:$Port/api/prospects" -Headers $headers -ContentType 'application/json' -Body $body | Out-Null
    $found = Invoke-RestMethod "http://127.0.0.1:$Port/api/prospects?text=smoke"
    if ($found.total -ne 1) { throw 'prospect not saved' }
    Write-Host 'Smoke test passed.'
} finally {
    & $exe stop --data-dir $data | Out-Null
    if (-not $proc.HasExited) { $proc | Stop-Process -Force }
    Remove-Item -Recurse -Force $data -ErrorAction SilentlyContinue
}
