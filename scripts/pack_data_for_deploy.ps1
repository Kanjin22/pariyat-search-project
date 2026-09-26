<#
.SYNOPSIS
    Pack the runtime data files (data/ folder) of pariyat-search into one zip
    so it can be uploaded to a new host (Oracle Cloud VPS / Docker host).

.DESCRIPTION
    - Only copies the files that are really needed at runtime.
    - Files that do not exist are skipped and reported (the app falls back to defaults).
    - A manifest.txt (file name, size, SHA256) is included inside the zip.
    - Zip entry names use forward slashes ("data/xxx.json") and are verified,
      so Linux 'unzip' extracts a real data/ folder.

.PARAMETER IncludeEnv
    Also include the local .env file in the package (contains secrets - handle with care).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\pack_data_for_deploy.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\pack_data_for_deploy.ps1 -IncludeEnv
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$DataDir,
    [string]$OutDir,
    [switch]$IncludeEnv
)

$ErrorActionPreference = 'Stop'

# Default project root = parent folder of this scripts folder
if (-not $ProjectRoot) {
    if ($PSScriptRoot) {
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    } else {
        $ProjectRoot = (Get-Location).Path
    }
}

if (-not $DataDir) { $DataDir = Join-Path $ProjectRoot 'data' }
if (-not $OutDir) { $OutDir = Join-Path $ProjectRoot 'dist' }

if (-not (Test-Path -LiteralPath $DataDir)) { throw "Data folder not found: $DataDir" }

# Keep this list in sync with deploy/required_data_files.txt
$requiredFiles = @(
    'api_snapshot_2568.json',
    'api_snapshot_2569.json',
    'exam_names_2568.json',
    'exam_names_2569.json',
    'exam_results.json',
    'exam_results_2568.json',
    'exam_results_2569.json',
    'manual_registrations_2568.json',
    'manual_registrations_2569.json',
    'pending_exam_results.json',
    'pending_exam_results_2568.json',
    'pending_exam_results_2569.json',
    'certificate_snapshot_2568.json',
    'certificate_snapshot_2569.json',
    'certificate_snapshot_all.json',
    'legacy_certificate_overrides.json',
    'legacy_certificate_deletions.json',
    'staff_accounts.json',
    'login_attempts.json',
    'data_source_settings.json',
    'bali_summary_2569.json',
    'analytics.sqlite3'
)

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$staging = Join-Path $env:TEMP "pariyat-seed-$stamp"
$stageData = Join-Path $staging 'data'
New-Item -ItemType Directory -Path $stageData -Force | Out-Null

$manifest = New-Object System.Collections.Generic.List[string]
$manifest.Add('# pariyat-search data package')
$manifest.Add("# created: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$manifest.Add("# source : $DataDir")
$manifest.Add('# columns: file_name <tab> size_bytes <tab> sha256')
$manifest.Add('')

$included = 0
$missing = New-Object System.Collections.Generic.List[string]

foreach ($name in $requiredFiles) {
    $src = Join-Path $DataDir $name
    if (-not (Test-Path -LiteralPath $src)) {
        $missing.Add($name)
        continue
    }
    Copy-Item -LiteralPath $src -Destination (Join-Path $stageData $name) -Force
    $hash = (Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash
    $size = (Get-Item -LiteralPath $src).Length
    $manifest.Add(("{0}`t{1}`t{2}" -f $name, $size, $hash))
    $included++
    Write-Host ("  + {0} ({1:N0} bytes)" -f $name, $size)
}

if ($IncludeEnv) {
    $envFile = Join-Path $ProjectRoot '.env'
    if (Test-Path -LiteralPath $envFile) {
        Copy-Item -LiteralPath $envFile -Destination (Join-Path $staging '.env') -Force
        Write-Host '  + .env (contains secrets - do not share this zip)'
    } else {
        Write-Host '  ! .env not found - skipped'
    }
}

$manifest.Add('')
$manifest.Add('# not found (skipped, app will use defaults): ' + ($missing -join ', '))
Set-Content -LiteralPath (Join-Path $staging 'manifest.txt') -Value $manifest -Encoding UTF8

if ($included -eq 0) {
    Remove-Item -LiteralPath $staging -Recurse -Force
    throw 'No data files found to pack - please check the -DataDir value.'
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$zipPath = Join-Path $OutDir "pariyat-data-$stamp.zip"
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }

# Build the zip manually so entry names always use forward slashes
# (Linux unzip then extracts a real "data/" folder).
$zipStream = [System.IO.File]::Open($zipPath, [System.IO.FileMode]::CreateNew)
try {
    $archive = New-Object System.IO.Compression.ZipArchive($zipStream, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        $items = @()
        foreach ($file in Get-ChildItem -LiteralPath $stageData -File) {
            $items += @{ Entry = "data/$($file.Name)"; Source = $file.FullName }
        }
        $items += @{ Entry = 'manifest.txt'; Source = (Join-Path $staging 'manifest.txt') }

        foreach ($item in $items) {
            $entry = $archive.CreateEntry($item.Entry, [System.IO.Compression.CompressionLevel]::Optimal)
            $entryStream = $entry.Open()
            try {
                $fileStream = [System.IO.File]::OpenRead($item.Source)
                try { $fileStream.CopyTo($entryStream) } finally { $fileStream.Dispose() }
            } finally { $entryStream.Dispose() }
        }
    } finally { $archive.Dispose() }
} finally { $zipStream.Dispose() }

# Verify: no entry name may contain a backslash
$reader = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $badNames = @($reader.Entries | Where-Object { $_.FullName.Contains('\') } | ForEach-Object { $_.FullName })
} finally { $reader.Dispose() }
if ($badNames.Count -gt 0) {
    throw ("Zip entry names contain backslash: {0}" -f ($badNames -join ', '))
}

Remove-Item -LiteralPath $staging -Recurse -Force

Write-Host ''
Write-Host ("Package created: {0}" -f $zipPath)
Write-Host ("Size: {0:N2} MB / files included: {1}" -f ((Get-Item $zipPath).Length / 1MB), $included)
if ($missing.Count -gt 0) {
    Write-Host ("Skipped (not found): {0}" -f ($missing -join ', ')) -ForegroundColor Yellow
}
Write-Host ''
Write-Host 'Next step - upload to the VPS (run this from the PC):'
Write-Host ("  scp `"{0}`" ubuntu@<VPS_IP>:/home/ubuntu/" -f $zipPath)
Write-Host 'Then on the VPS:'
Write-Host ("  sudo bash /opt/pariyat-search/deploy/seed_data.sh /home/ubuntu/{0}" -f (Split-Path $zipPath -Leaf))

