param([Parameter(Mandatory=$true)][string]$Spec)
$ErrorActionPreference = 'Stop'
function Call-Com($Object, [string]$Name, [object[]]$Arguments) {
    $Object.GetType().InvokeMember($Name, [Reflection.BindingFlags]::InvokeMethod, $null, $Object, $Arguments)
}
function Set-Com($Object, [string]$Name, [object[]]$Arguments) {
    $Object.GetType().InvokeMember($Name, [Reflection.BindingFlags]::SetProperty, $null, $Object, $Arguments)
}
function Get-Com($Object, [string]$Name, [object[]]$Arguments) {
    $Object.GetType().InvokeMember($Name, [Reflection.BindingFlags]::GetProperty, $null, $Object, $Arguments)
}
$plan = Get-Content -LiteralPath $Spec -Raw | ConvertFrom-Json
$root = [IO.Path]::GetFullPath((Split-Path -Parent $Spec))
$target = [IO.Path]::GetFullPath([string]$plan.output)
if ([IO.Path]::GetDirectoryName($target) -ne $root -or [IO.Path]::GetExtension($target) -ne '.msi' -or (Test-Path -LiteralPath $target)) {
    throw 'The MSI must be a new file inside the exclusive build folder.'
}
$installer = New-Object -ComObject WindowsInstaller.Installer
$database = Call-Com $installer 'OpenDatabase' @($plan.output, 3)
try {
    foreach ($table in $plan.tables) {
        $view = Call-Com $database 'OpenView' @($table.sql)
        $null = Call-Com $view 'Execute' @()
        $null = Call-Com $view 'Close' @()
        $names = ($table.columns | ForEach-Object { '`' + $_ + '`' }) -join ', '
        $marks = ($table.columns | ForEach-Object { '?' }) -join ', '
        $view = Call-Com $database 'OpenView' @('INSERT INTO `' + $table.name + '` (' + $names + ') VALUES (' + $marks + ')')
        foreach ($row in $table.rows) {
            $record = Call-Com $installer 'CreateRecord' @([int]$table.columns.Count)
            for ($i = 0; $i -lt $row.Count; $i++) {
                if ($null -eq $row[$i]) { continue }
                if ($row[$i] -is [PSCustomObject] -and $row[$i].stream) {
                    $null = Call-Com $record 'SetStream' @([int]($i + 1), [string]$row[$i].stream)
                } elseif ($row[$i] -is [long] -or $row[$i] -is [int]) {
                    $null = Set-Com $record 'IntegerData' @([int]($i + 1), [int]$row[$i])
                } else { $null = Set-Com $record 'StringData' @([int]($i + 1), [string]$row[$i]) }
            }
            $null = Call-Com $view 'Execute' @($record)
        }
        $null = Call-Com $view 'Close' @()
    }
    $view = Call-Com $database 'OpenView' @('INSERT INTO `_Streams` (`Name`, `Data`) VALUES (?, ?)')
    $record = Call-Com $installer 'CreateRecord' @(2)
    $null = Set-Com $record 'StringData' @(1, 'payload.cab')
    $null = Call-Com $record 'SetStream' @(2, [string]$plan.cab)
    $null = Call-Com $view 'Execute' @($record)
    $null = Call-Com $view 'Close' @()
    $summary = Get-Com $database 'SummaryInformation' @(20)
    foreach ($pair in @(@(1,1252),@(2,'Installation Database'),@(3,('A2 Racers Revival ' + $plan.version)),@(4,'A2 Revival fan project'),@(5,'Installer'),@(7,'x64;1043'),@(9,[string]$plan.package_code),@(14,200),@(15,2),@(18,'Windows Installer COM / makecab'))) {
        $null = Set-Com $summary 'Property' @([int]$pair[0],$pair[1])
    }
    $null = Call-Com $summary 'Persist' @()
    $null = Call-Com $database 'Commit' @()
} catch {
    Write-Error ('MSI authoring failed: ' + $_.Exception.Message)
    throw
} finally {
    $summary = $null; $record = $null; $view = $null; $database = $null; $installer = $null
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
