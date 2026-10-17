param([Parameter(Mandatory=$true)][string]$Spec, [string]$Output)
# Read-only database and embedded-stream audit. Never installs or starts the MSI.
$ErrorActionPreference = 'Stop'

function Call-Com($Object, [string]$Name, [object[]]$Arguments) {
    $Object.GetType().InvokeMember($Name, [Reflection.BindingFlags]::InvokeMethod, $null, $Object, $Arguments)
}
function Get-Com($Object, [string]$Name, [object[]]$Arguments) {
    $Object.GetType().InvokeMember($Name, [Reflection.BindingFlags]::GetProperty, $null, $Object, $Arguments)
}
function Row-Key([object[]]$Values) {
    $strings = @($Values | ForEach-Object { if ($null -eq $_) { '' } else { [string]$_ } })
    ConvertTo-Json -InputObject $strings -Compress
}
function Assert-Rows($Expected, $Actual, [string]$Name) {
    $left = [Collections.Generic.List[string]]::new()
    $right = [Collections.Generic.List[string]]::new()
    foreach ($row in $Expected) { $left.Add((Row-Key $row)) }
    foreach ($row in $Actual) { $right.Add((Row-Key $row)) }
    $left.Sort([StringComparer]::Ordinal); $right.Sort([StringComparer]::Ordinal)
    if (($left.Count -ne $right.Count) -or (($left -join "`n") -cne ($right -join "`n"))) {
        throw ('MSI database differs from the build plan: ' + $Name)
    }
}
function Read-StreamHash($Database, [string]$Sql, [string]$Source) {
    $view = Call-Com $Database 'OpenView' @($Sql)
    try {
        $null = Call-Com $view 'Execute' @()
        $record = Call-Com $view 'Fetch' @()
        if ($null -eq $record) { throw 'Embedded MSI stream is missing.' }
        $size = [int](Get-Com $record 'DataSize' @(1))
        $hash = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
        try {
            $encoding = [Text.Encoding]::GetEncoding(28591)
            $remaining = $size
            while ($remaining -gt 0) {
                $length = [Math]::Min(65536, $remaining)
                $chunk = Call-Com $record 'ReadStream' @(1, [int]$length, 1)
                if ($chunk.Length -ne $length) { throw 'Truncated embedded MSI stream.' }
                $hash.AppendData($encoding.GetBytes($chunk)); $remaining -= $length
            }
            $digest = ([BitConverter]::ToString($hash.GetHashAndReset())).Replace('-', '').ToLowerInvariant()
        } finally { $hash.Dispose() }
        if ($null -ne (Call-Com $view 'Fetch' @())) { throw 'Duplicate embedded MSI stream.' }
        $sourceFile = Get-Item -LiteralPath $Source
        $sourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
        if (($sourceFile.Length -ne $size) -or ($sourceHash -cne $digest)) {
            throw 'Embedded MSI stream differs from the reviewed build input.'
        }
        return @{ size = $size; sha256 = $digest }
    } finally { $null = Call-Com $view 'Close' @() }
}

$plan = Get-Content -LiteralPath $Spec -Raw | ConvertFrom-Json
if (-not $Output) { $Output = Join-Path (Split-Path -Parent $Spec) 'database-audit.json' }
if (Test-Path -LiteralPath $Output) { throw 'Audit output already exists; choose a new output file.' }
$expectedNames = @($plan.tables | ForEach-Object { [string]$_.name })
if (($expectedNames -contains 'CustomAction') -or ($expectedNames -contains 'RemoveFile')) {
    throw 'Custom actions and wildcard deletion are not part of this installer.'
}
foreach ($table in $plan.tables) {
    foreach ($identifier in @($table.name) + @($table.columns)) {
        if ($identifier -cnotmatch '^[A-Za-z_][A-Za-z0-9_]*$') { throw 'Invalid MSI table or column name.' }
    }
}
$installer = New-Object -ComObject WindowsInstaller.Installer
$database = Call-Com $installer 'OpenDatabase' @([string]$plan.output, 0)
$snapshot = [ordered]@{ schema = 1; tables_match_plan = $false; streams = [ordered]@{}; installed = $false }
try {
    $view = Call-Com $database 'OpenView' @('SELECT `Name` FROM `_Tables`')
    $null = Call-Com $view 'Execute' @()
    $names = @()
    while ($null -ne ($record = Call-Com $view 'Fetch' @())) { $names += [string](Get-Com $record 'StringData' @(1)) }
    $null = Call-Com $view 'Close' @()
    if ((@($names | Sort-Object) -join ',') -cne (@($expectedNames | Sort-Object) -join ',')) {
        throw 'MSI has missing or unexpected tables.'
    }
    $view = Call-Com $database 'OpenView' @('SELECT `Name` FROM `_Streams`')
    $null = Call-Com $view 'Execute' @()
    $streamNames = @()
    while ($null -ne ($record = Call-Com $view 'Fetch' @())) { $streamNames += [string](Get-Com $record 'StringData' @(1)) }
    $null = Call-Com $view 'Close' @()
    $allowedStreams = @('payload.cab', 'Icon.A2Icon', ([string][char]5 + 'SummaryInformation'))
    if ((@($streamNames | Sort-Object) -join ',') -cne (@($allowedStreams | Sort-Object) -join ',')) {
        throw 'MSI has missing or unexpected embedded streams.'
    }
    $view = Call-Com $database 'OpenView' @('SELECT `Name` FROM `_Storages`')
    $null = Call-Com $view 'Execute' @()
    if ($null -ne (Call-Com $view 'Fetch' @())) { throw 'MSI contains an unexpected embedded substorage.' }
    $null = Call-Com $view 'Close' @()
    foreach ($table in $plan.tables) {
        $indices = @()
        for ($i = 0; $i -lt $table.columns.Count; $i++) {
            if (-not ($table.name -eq 'Icon' -and $table.columns[$i] -eq 'Data')) { $indices += $i }
        }
        $columns = @($indices | ForEach-Object { '`' + $table.columns[$_] + '`' })
        $sql = 'SELECT ' + ($columns -join ', ') + ' FROM `' + $table.name + '`'
        $view = Call-Com $database 'OpenView' @($sql)
        $null = Call-Com $view 'Execute' @()
        $rows = [Collections.Generic.List[object]]::new()
        while ($null -ne ($record = Call-Com $view 'Fetch' @())) {
            $row = @()
            for ($i = 1; $i -le $columns.Count; $i++) { $row += [string](Get-Com $record 'StringData' @($i)) }
            $rows.Add($row)
        }
        $expected = [Collections.Generic.List[object]]::new()
        foreach ($row in $table.rows) { $expected.Add(@($indices | ForEach-Object { $row[$_] })) }
        Assert-Rows $expected $rows $table.name
        $null = Call-Com $view 'Close' @()
    }
    $snapshot.tables_match_plan = $true
    $snapshot.table_count = $expectedNames.Count
    $snapshot.streams.Cabinet = Read-StreamHash $database 'SELECT `Data` FROM `_Streams` WHERE `Name` = ''payload.cab''' ([string]$plan.cab)
    $snapshot.streams.Icon = Read-StreamHash $database 'SELECT `Data` FROM `Icon` WHERE `Name` = ''A2Icon''' ([string]$plan.icon)
    $summary = Get-Com $database 'SummaryInformation' @(0)
    if (([string](Get-Com $summary 'Property' @(7))) -cne 'x64;1043') { throw 'Wrong MSI architecture/language.' }
    if (([string](Get-Com $summary 'Property' @(9))) -cne [string]$plan.package_code) { throw 'Wrong MSI package identity.' }
    $snapshot.msi_sha256 = (Get-FileHash -LiteralPath $plan.output -Algorithm SHA256).Hash.ToLowerInvariant()
    $outputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
    $stream = [IO.File]::Open($outputPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
        $writer.WriteLine(($snapshot | ConvertTo-Json -Depth 10)); $writer.Flush()
    } finally { if ($writer) { $writer.Dispose() } else { $stream.Dispose() } }
    Write-Output ('Verified ' + $expectedNames.Count + ' MSI tables and embedded cabinet/icon hashes; no installation performed.')
} finally {
    $record = $null; $view = $null; $summary = $null; $database = $null; $installer = $null
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
