#Requires -Version 5.1
param([switch]$CheckOnly, [switch]$Diagnostic, [switch]$Dismount, [string]$GameArchive,
      [ValidateRange(-1, 120)][int]$RaceFPSLimit = -1,
      [ValidateSet('original', 'gdi', 'svga', 'no-dither')][string]$MapMode,
      [ValidateSet('original', 'borderless-4-3', 'hd-1280x960', 'hd-1280x960-fake', 'hd-1920x1440')][string]$DisplayProfile,
      [string]$ProgressPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$kitRoot = Split-Path -Parent $PSScriptRoot

# A shortcut or cmd started from PowerShell 7 can inherit its module path.
# Resolve Windows PowerShell's own built-in modules first, in this process only.
if ($PSVersionTable.PSVersion.Major -lt 6) {
    $env:PSModulePath = (Join-Path $PSHOME 'Modules') + [IO.Path]::PathSeparator + $env:PSModulePath
}

function Assert-PortablePath([string]$Path) {
    $candidate = [IO.Path]::GetFullPath($Path)
    while ($candidate) {
        if (Test-Path -LiteralPath $candidate) {
            if ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Testpakket staat achter een link/reparse point; kies een gewone schrijfbare map.'
            }
        }
        $parent = [IO.Directory]::GetParent($candidate)
        $candidate = if ($parent) { $parent.FullName } else { $null }
    }
}

try {
    if (-not [Environment]::Is64BitOperatingSystem -or
        [Environment]::GetEnvironmentVariable('PROCESSOR_ARCHITECTURE', 'Machine') -eq 'ARM64') {
        throw 'Dit testpakket is voor Windows x64 op Intel/AMD.'
    }
    Assert-PortablePath $kitRoot
    $publicMarker = Join-Path $kitRoot 'public-release.json'
    if (Test-Path -LiteralPath $publicMarker) {
        Assert-PortablePath $publicMarker
        if ((Get-Item -LiteralPath $publicMarker).Length -gt 4096) { throw 'Openbaar releaserecord is te groot.' }
        $publicRelease = [IO.File]::ReadAllText($publicMarker) | ConvertFrom-Json
        if ($publicRelease.schema -ne 1 -or $publicRelease.component_delivery -ne 'verified-provider-download' -or $publicRelease.games_bundled -ne $false) { throw 'Onbekende openbare release.' }
        & (Join-Path $PSScriptRoot 'Initialize-A2Public.ps1') -KitPath $kitRoot -ProgressPath $ProgressPath
        if (-not $?) { throw 'Componentdownload of hashcontrole faalde; niets gestart.' }
    }
    $pythonArchive = Join-Path $kitRoot 'payload\python-3.13.16-embed-amd64.zip'
    $pin = '97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297'
    Assert-PortablePath $pythonArchive
    if ((Get-FileHash -LiteralPath $pythonArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pin) {
        throw 'Python-archief ontbreekt of wijkt af van de officiële checksum.'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $pythonRoot = Join-Path $kitRoot 'local\portable-runtime\python'
    Assert-PortablePath $pythonRoot
    $archive = [IO.Compression.ZipFile]::OpenRead($pythonArchive)
    try {
        if ($archive.Entries.Count -gt 100) { throw 'Python-archief heeft te veel entries.' }
        $total = 0L
        $seen = @{}
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName
            if (-not $name -or $name -match '[\\/:]' -or $name -in @('.', '..') -or $seen.ContainsKey($name.ToLowerInvariant())) {
                throw 'Onveilige Python-archiefnaam.'
            }
            $seen[$name.ToLowerInvariant()] = $true
            $total += $entry.Length
        }
        if ($total -gt 40MB) { throw 'Python-archief is te groot.' }
        if (-not (Test-Path -LiteralPath $pythonRoot)) { $null = [IO.Directory]::CreateDirectory($pythonRoot) }
        foreach ($entry in $archive.Entries) {
            $target = Join-Path $pythonRoot $entry.FullName
            Assert-PortablePath $target
            if (Test-Path -LiteralPath $target) {
                $stream = $entry.Open()
                $digest = [Security.Cryptography.SHA256]::Create()
                try { $expected = [BitConverter]::ToString($digest.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
                finally { $stream.Dispose(); $digest.Dispose() }
                if ((Get-FileHash -LiteralPath $target).Hash.ToLowerInvariant() -ne $expected) {
                    throw 'Bestaande portable Python is gewijzigd; gebruik een verse uitgepakte kit.'
                }
            } else {
                $source = $entry.Open()
                $out = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
                try { $source.CopyTo($out) } finally { $source.Dispose(); $out.Dispose() }
            }
        }
    } finally { $archive.Dispose() }
    $pythonPath = Join-Path $pythonRoot 'python.exe'
    Write-Host 'Portable runtimes en compatibiliteitscomponenten controleren...'
    & $pythonPath -B (Join-Path $PSScriptRoot 'portable_test.py') setup
    if ($LASTEXITCODE -ne 0) { throw 'Componentvoorbereiding faalde; niets gestart.' }
    if (Test-Path -LiteralPath (Join-Path $kitRoot 'release-manifest.json')) {
        & $pythonPath -B (Join-Path $PSScriptRoot 'portable_launcher.py') setup-assets
        if ($LASTEXITCODE -ne 0) { throw 'Launcher-artvoorbereiding faalde; niets gestart.' }
    }
    $pwshPath = Join-Path $kitRoot 'local\portable-runtime\powershell\pwsh.exe'
    $sessionArguments = @('-NoLogo', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $PSScriptRoot 'Run-A2Portable.ps1'), '-PythonPath', $pythonPath)
    if ($CheckOnly) { $sessionArguments += '-CheckOnly' }
    if ($Diagnostic) { $sessionArguments += '-Diagnostic' }
    if ($Dismount) { $sessionArguments += '-Dismount' }
    if ($GameArchive) { $sessionArguments += @('-GameArchive', $GameArchive) }
    if ($RaceFPSLimit -ge 0) { $sessionArguments += @('-RaceFPSLimit', $RaceFPSLimit) }
    if ($MapMode) { $sessionArguments += @('-MapMode', $MapMode) }
    if ($DisplayProfile) { $sessionArguments += @('-DisplayProfile', $DisplayProfile) }
    & $pwshPath @sessionArguments
    if ($LASTEXITCODE -ne 0) { throw 'Proefstart faalde; zie de bovenstaande fout en lokale logs.' }
} catch {
    Write-Host ('A2-test gestopt: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
