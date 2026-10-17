param([Parameter(Mandatory=$true)][string]$ProductName)
# Read only the two shortcuts owned by the synthetic lifecycle test.
$ErrorActionPreference = 'Stop'
if ($ProductName -cnotmatch '^A2 Revival installer test [0-9a-f]{12}$') {
    throw 'Only the isolated installer test product is accepted.'
}
$desktop = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) ($ProductName + '.lnk')
$programs = Join-Path ([Environment]::GetFolderPath('Programs')) $ProductName
$menu = Join-Path $programs ($ProductName + '.lnk')
$shell = New-Object -ComObject WScript.Shell
$rows = foreach ($path in @($desktop, $menu)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Expected test shortcut is missing.' }
    $link = $shell.CreateShortcut($path)
    # Never call Save(): inspecting an existing shortcut does not modify it.
    [ordered]@{ path=$path; target=$link.TargetPath; icon=$link.IconLocation; arguments=$link.Arguments }
}
ConvertTo-Json -InputObject @($rows) -Compress
