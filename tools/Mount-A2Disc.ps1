#Requires -Version 7.0
<#
.SYNOPSIS
Bereidt een bekende lokale game-ISO voor en mount uitsluitend die cd read-only.
.DESCRIPTION
Leest local/media/<game>/iso2048/disc.iso en maakt een aparte ready/disc.iso.
Behoudt bronbytes en bron-ACL. Alleen de eigen kopie krijgt een expliciete
ReadAndExecute|WriteAttributes-ACE voor de huidige gebruiker. Windows kan de
ISO-file-ACL gebruiken voor het virtuele cd-apparaat; OWNER RIGHTS alleen is
daarvoor onvoldoende gebleken. Verandert geen OS-beleid, drivers of device-ACL.
-Dismount demonteert uitsluitend de bekende eigen ready/disc.iso.
#>
[CmdletBinding()]
param(
    [ValidateSet('a2racer1', 'a2racer2')][string]$Game = 'a2racer1',
    [switch]$Dismount
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-DiscRealPath([string]$Path) {
    $candidate = [System.IO.Path]::GetFullPath($Path)
    while ($candidate) {
        $item = $null
        try { $item = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop }
        catch {
            if ($_.CategoryInfo.Category -ne [System.Management.Automation.ErrorCategory]::ObjectNotFound) { throw }
        }
        if ($item -and ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            throw "Cd-pad bevat een link/reparse point: $candidate"
        }
        if ($item) {
            # NTFS hardlinks do not carry ReparsePoint, but share their ACL.
            # Granting file access through one could alter the original ISO
            # or another file. Reject them before any ACL or mount operation.
            $linkType = $item.PSObject.Properties['LinkType']
            if ($linkType -and $linkType.Value -eq 'HardLink') {
                throw "Cd-pad bevat een hardlink met gedeelde ACL: $candidate"
            }
        }
        $parent = [System.IO.Directory]::GetParent($candidate)
        $candidate = if ($parent) { $parent.FullName } else { $null }
    }
}

function Get-DiscProfile([string]$GameName) {
    switch ($GameName) {
        'a2racer1' { return @{ sha256 = 'a35120f939d56b93fabbf910b08500a95dd8601b28350ac0609a480bb387cc32'; expected_file = 'A2INTRO.SMK' } }
        'a2racer2' { return @{ sha256 = '8a0755bdbde7b526763157e8034403f9d2a732d36db1fad93c2fdc9eb67f1d7d'; expected_file = 'DATA\INTRO.SMK' } }
        default { throw 'Onbekende game.' }
    }
}

function Get-DiscPaths([string]$Workspace, [string]$GameName) {
    $null = Get-DiscProfile $GameName
    $workspaceRoot = [System.IO.Path]::GetFullPath($Workspace)
    $mediaRoot = Join-Path (Join-Path $workspaceRoot 'local/media') $GameName
    $paths = @{ workspace = $workspaceRoot; source = Join-Path $mediaRoot 'iso2048/disc.iso'; ready = Join-Path $mediaRoot 'ready/disc.iso'; report_root = Join-Path (Join-Path $workspaceRoot 'reports/runtime') "$GameName/disc-mount" }
    $prefix = $workspaceRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    foreach ($path in @($paths.source, $paths.ready, $paths.report_root)) {
        if (-not [System.IO.Path]::GetFullPath($path).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Cd-pad valt buiten workspace.' }
        Assert-DiscRealPath $path
    }
    return $paths
}

function Assert-DiscHash([string]$Path, [string]$Expected) {
    Assert-DiscRealPath $Path
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer) { throw "Geen reguliere ISO-file: $Path" }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if ($actual -ne $Expected) { throw "Onbekende ISO-versie/hash: $Path" }
    return $actual
}

function Get-DiscAclRecord([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    return @{ owner = $acl.Owner; sddl = $acl.Sddl }
}

function Get-CurrentDiscUserSid {
    return [System.Security.Principal.WindowsIdentity]::GetCurrent().User
}

function Grant-DiscUserFileAccess([string]$Path) {
    Assert-DiscRealPath $Path
    $sid = Get-CurrentDiscUserSid
    $rights = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [System.Security.AccessControl.FileSystemRights]::WriteAttributes
    $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
    $rules = @($acl.GetAccessRules($true, $false, [System.Security.Principal.SecurityIdentifier]) | Where-Object { $_.IdentityReference.Value -eq $sid.Value })
    if (@($rules | Where-Object { $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Deny }).Count -gt 0) {
        throw 'Eigen ISO heeft een expliciete deny-ACE voor de huidige gebruiker; die wordt niet verwijderd.'
    }
    $alreadyAllowed = @($rules | Where-Object { $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow -and ($_.FileSystemRights -band $rights) -eq $rights }).Count -gt 0
    if (-not $alreadyAllowed) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid, $rights, [System.Security.AccessControl.AccessControlType]::Allow)
        $null = $acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $Path -AclObject $acl -ErrorAction Stop
    }
    return @{ user_sid = $sid.Value; requested_rights = $rights.ToString(); changed = -not $alreadyAllowed }
}

function Prepare-ReadyDisc($Paths, $Profile) {
    $sourceHash = Assert-DiscHash $Paths.source $Profile.sha256
    $sourceAcl = Get-DiscAclRecord $Paths.source
    $readyRoot = Split-Path -Parent $Paths.ready
    $reused = Test-Path -LiteralPath $Paths.ready
    if ($reused) { $null = Assert-DiscHash $Paths.ready $Profile.sha256 }
    else {
        Assert-DiscRealPath $readyRoot
        $null = [System.IO.Directory]::CreateDirectory($readyRoot)
        $staging = Join-Path $readyRoot ('.disc-' + [Guid]::NewGuid().ToString('N') + '.tmp')
        try {
            Assert-DiscRealPath $staging
            [System.IO.File]::Copy($Paths.source, $staging, $false)
            $null = Assert-DiscHash $staging $Profile.sha256
            $null = Assert-DiscHash $Paths.source $Profile.sha256
            # Move never overwrites a ready file that appeared during copying.
            Assert-DiscRealPath $Paths.ready
            [System.IO.File]::Move($staging, $Paths.ready, $false)
        } finally {
            if ([System.IO.File]::Exists($staging)) {
                Assert-DiscRealPath $staging
                [System.IO.File]::Delete($staging)
            }
        }
    }
    $readyAclBefore = Get-DiscAclRecord $Paths.ready
    $grant = Grant-DiscUserFileAccess $Paths.ready
    $readyHash = Assert-DiscHash $Paths.ready $Profile.sha256
    $sourceAfter = Assert-DiscHash $Paths.source $Profile.sha256
    $sourceAclAfter = Get-DiscAclRecord $Paths.source
    if ($sourceAcl.sddl -ne $sourceAclAfter.sddl -or $sourceAcl.owner -ne $sourceAclAfter.owner) { throw 'Bron-ACL veranderde tijdens cdvoorbereiding.' }
    return @{ reused = $reused; source_sha256 = $sourceHash; source_sha256_after = $sourceAfter; ready_sha256 = $readyHash; source_acl_before = $sourceAcl; source_acl_after = $sourceAclAfter; ready_acl_before = $readyAclBefore; ready_acl_after = Get-DiscAclRecord $Paths.ready; file_access = $grant }
}

function Mount-ReadyDisc($Paths, $Profile) {
    $null = Assert-DiscHash $Paths.ready $Profile.sha256
    $image = Get-DiskImage -ImagePath $Paths.ready -ErrorAction Stop
    $mountedThisRun = $false
    $mountAttempted = $false
    try {
        if (-not $image.Attached) {
            $mountAttempted = $true
            $image = Mount-DiskImage -ImagePath $Paths.ready -StorageType ISO -Access ReadOnly -PassThru -ErrorAction Stop
            $mountedThisRun = $true
        }
        if (-not $image.Attached) { throw 'Eigen ISO werd niet aangesloten.' }
        $volumes = @($image | Get-Volume -ErrorAction Stop | Where-Object { $_.DriveLetter } | Sort-Object DriveLetter)
        if ($volumes.Count -ne 1) { throw 'Eigen cd heeft niet precies een volume met driveletter.' }
        $driveLetter = ([string]$volumes[0].DriveLetter).ToUpperInvariant()
        if ($driveLetter -notmatch '^[A-Z]$') { throw 'Ongeldige driveletter voor eigen cd.' }
        $ownDisk = @(Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DriveType=5" -ErrorAction Stop | Sort-Object DeviceID)
        $driveId = $driveLetter + ':'
        if ($ownDisk.Count -eq 0 -or $ownDisk[0].DeviceID -ne $driveId) {
            throw "Eigen cd ($driveId) is niet de alfabetisch eerste cdrom; andere images/drives worden niet gedemonteerd."
        }
        $expectedFile = Join-Path ($driveId + '\') $Profile.expected_file
        # A successful open/read proves more than a drive letter or Attached=true.
        Test-DiscIntroReadable $expectedFile
        return @{ mounted_this_run = $mountedThisRun; already_attached = -not $mountedThisRun; device_path = $image.DevicePath; drive_letter = $driveLetter; filesystem = $volumes[0].FileSystem; expected_file = $expectedFile; expected_file_readable = $true; first_cdrom = $driveId }
    } catch {
        if ($mountAttempted -and -not $mountedThisRun) {
            # The storage cmdlet can throw after attaching. Only the exact
            # previously unattached own image is eligible for this cleanup.
            try { $mountedThisRun = [bool](Get-DiskImage -ImagePath $Paths.ready -ErrorAction Stop).Attached }
            catch { Write-Warning 'Status van eigen ISO na mountfout kon niet worden bepaald; geen andere image wordt gedemonteerd.' }
        }
        if ($mountedThisRun) {
            try { $null = Dismount-DiskImage -ImagePath $Paths.ready -ErrorAction Stop }
            catch { throw "Cdcontrole faalde; demontage van uitsluitend de eigen ISO faalde ook: $($_.Exception.Message)" }
        }
        throw
    }
}

function Test-DiscIntroReadable([string]$Path) {
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try { $firstByte = $stream.ReadByte() } finally { $stream.Dispose() }
    if ($firstByte -lt 0) { throw 'Verwacht introbestand op cd is leeg.' }
}

function Dismount-ReadyDisc($Paths, $Profile) {
    $null = Assert-DiscHash $Paths.ready $Profile.sha256
    $image = Get-DiskImage -ImagePath $Paths.ready -ErrorAction Stop
    if ($image.Attached) { $null = Dismount-DiskImage -ImagePath $Paths.ready -ErrorAction Stop }
    return @{ previously_attached = [bool]$image.Attached; image_path = $Paths.ready; dismounted = [bool]$image.Attached }
}

$workspacePath = Split-Path -Parent $PSScriptRoot
$profile = Get-DiscProfile $Game
$paths = Get-DiscPaths $workspacePath $Game
$null = [System.IO.Directory]::CreateDirectory($paths.report_root)
$reportPath = Join-Path $paths.report_root ((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N') + '.json')
$report = [ordered]@{ game = $Game; action = if ($Dismount) { 'dismount' } else { 'mount' }; timestamp_utc = [DateTime]::UtcNow.ToString('o'); source_path = $paths.source; ready_path = $paths.ready; known_iso_sha256 = $profile.sha256; preparation = $null; result = $null; error = $null }
try {
    if ($Dismount) { $report.result = Dismount-ReadyDisc $paths $profile }
    else {
        $report.preparation = Prepare-ReadyDisc $paths $profile
        $report.result = Mount-ReadyDisc $paths $profile
        Write-Host "Eigen cd klaar op $($report.result.drive_letter):; introbestand leesbaar. Geen game gestart."
    }
} catch { $report.error = $_.Exception.Message; throw }
finally {
    Assert-DiscRealPath $reportPath
    [System.IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 10), [System.Text.UTF8Encoding]::new($false))
    Write-Host "Cdrapport: $reportPath"
}
