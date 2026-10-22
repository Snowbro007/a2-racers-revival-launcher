#Requires -Version 5.1
[CmdletBinding()]
param([string]$KitPath = (Split-Path -Parent $PSScriptRoot), [switch]$CheckOnly, [string]$ProgressPath,
      [switch]$LauncherOnly, [switch]$SkipMedia)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-A2PublicProviders([switch]$LauncherOnly, [switch]$SkipMedia) {
    $providers = @(
        @{name='python-3.13.16-embed-amd64.zip';sha256='97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297';url='https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip'},
        @{name='PowerShell-7.6.5-win-x64.zip';sha256='32eb8f6cdce08f86e987d625a2733e54ac3e289ae7e1621b14c0b5bcec2434ea';url='https://github.com/PowerShell/PowerShell/releases/download/v7.6.5/PowerShell-7.6.5-win-x64.zip'},
        @{name='cnc-ddraw-v7.0.0.0.zip';sha256='f9640f69c2b8c012b97720ce0a9aac483989563908fc19446b9d1ba16e7239d6';url='https://github.com/FunkyFr3sh/cnc-ddraw/releases/download/v7.0.0.0/cnc-ddraw.zip'},
        @{name='dgVoodoo2_87_5.zip';sha256='5ffde6927f7355ca3fdd5d785b581256a8e6539fa13e395a891ade6ba1040850';url='https://github.com/dege-diosg/dgVoodoo2/releases/download/v2.87.5/dgVoodoo2_87_5.zip'},
        @{name='ffmpeg-9.0.2-essentials_build.zip';sha256='60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba';url='https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip'}
    )
    if($LauncherOnly){return @($providers | Where-Object {$_.name -eq 'python-3.13.16-embed-amd64.zip'})}
    if($SkipMedia){return @($providers | Where-Object {$_.name -ne 'ffmpeg-9.0.2-essentials_build.zip'})}
    return $providers
}

function Assert-A2PublicPath([string]$Path) {
    $candidate=[IO.Path]::GetFullPath($Path)
    while($candidate){
        if(Test-Path -LiteralPath $candidate){
            if((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Componentpad loopt via een link; kies een gewone schrijfbare map.'}
        }
        $parent=[IO.Directory]::GetParent($candidate)
        $candidate=if($parent){$parent.FullName}else{$null}
    }
}

function Test-A2ProviderFile([string]$Path,[string]$Pin) {
    Assert-A2PublicPath $Path
    if(-not [IO.File]::Exists($Path)){return $false}
    $file=Get-Item -LiteralPath $Path
    if($file.Length -le 0 -or $file.Length -gt 180MB){throw 'Componentbestand heeft een ongeldige grootte.'}
    $stream=[IO.File]::OpenRead($Path);$digest=[Security.Cryptography.SHA256]::Create()
    try{$actual=[BitConverter]::ToString($digest.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}
    finally{$stream.Dispose();$digest.Dispose()}
    if($actual -ne $Pin){throw ('Componenthash wijkt af: '+$file.Name+'. Gebruik een verse downloadmap.')}
    return $true
}

function Get-A2DownloadMilliseconds {
    return [double][Diagnostics.Stopwatch]::GetTimestamp() * 1000 / [Diagnostics.Stopwatch]::Frequency
}

function Wait-A2DownloadTask($Task,[double]$DeadlineMilliseconds,[scriptblock]$Clock,[string]$Component) {
    $remaining=$DeadlineMilliseconds-(& $Clock)
    if($remaining -le 0){throw ('Downloadtijd verstreken voor '+$Component+'; probeer later opnieuw.')}
    $wait=[int][Math]::Min(30000,[Math]::Ceiling($remaining))
    if(-not $Task.Wait($wait)){throw ('Componentdownload reageert niet: '+$Component+'. Probeer later opnieuw.')}
    if((& $Clock) -ge $DeadlineMilliseconds){throw ('Downloadtijd verstreken voor '+$Component+'; probeer later opnieuw.')}
}

function Write-A2DownloadProgress([string]$Component,[long]$Received,[long]$ExpectedLength) {
    $amount=if($ExpectedLength -ge 0){[string]$Received+' van '+$ExpectedLength+' bytes'}else{[string]$Received+' bytes'}
    Write-Host ('Component downloaden: '+$Component+' - '+$amount)
}

function Write-A2ComponentState([string]$Root,[string]$ProgressPath,
        [ValidateSet('checking','downloading','complete','error')][string]$Stage,
        [string]$Component='',[long]$Received=0,[long]$ExpectedLength=-1) {
    if(-not $ProgressPath){return}
    Assert-A2PublicPath $Root
    $expected=[IO.Path]::GetFullPath((Join-Path $Root 'local\launcher\component-progress.json'))
    if([IO.Path]::GetFullPath($ProgressPath) -ne $expected){throw 'Ongeldig componentvoortgangspad.'}
    Assert-A2PublicPath $expected
    $folder=Split-Path -Parent $expected
    $temporary=Join-Path $folder ('.component-progress-'+[Guid]::NewGuid().ToString('N')+'.tmp')
    Assert-A2PublicPath $temporary
    $value=[ordered]@{schema=1;stage=$Stage;component=$Component;received=$Received;total=if($ExpectedLength -ge 0){$ExpectedLength}else{$null}}
    $bytes=[Text.Encoding]::UTF8.GetBytes(($value | ConvertTo-Json -Compress))
    try{
        # This optional display record must never fail a valid download merely
        # because a reader locks it or this filesystem cannot replace a file.
        # Path validation remains outside the best-effort I/O catch blocks.
        try{
            [IO.Directory]::CreateDirectory($folder) | Out-Null
            $stream=[IO.File]::Open($temporary,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
            try{$stream.Write($bytes,0,$bytes.Length)}finally{$stream.Dispose()}
        }catch [IO.IOException],[UnauthorizedAccessException],[NotSupportedException]{return}
        Assert-A2PublicPath $expected
        try{
            if([IO.File]::Exists($expected)){[IO.File]::Replace($temporary,$expected,[NullString]::Value)}
            else{[IO.File]::Move($temporary,$expected)}
        }catch [IO.IOException],[UnauthorizedAccessException],[NotSupportedException]{return}
    }finally{
        if([IO.File]::Exists($temporary)){
            Assert-A2PublicPath $temporary
            try{[IO.File]::Delete($temporary)}catch [IO.IOException],[UnauthorizedAccessException],[NotSupportedException]{}
        }
    }
}

function Get-A2DownloadPartial([string]$Destination,[string]$Pin) {
    if($Pin -notmatch '^[a-f0-9]{64}$'){throw 'Ongeldige componentpin.'}
    $partial=Join-Path ([IO.Path]::GetDirectoryName($Destination)) ('.'+[IO.Path]::GetFileName($Destination)+'-'+$Pin+'.partial')
    Assert-A2PublicPath $partial
    if(Test-Path -LiteralPath $partial){
        $item=Get-Item -LiteralPath $partial -Force
        if($item.PSIsContainer -or $item.Length -gt 180MB){throw 'Ongeldig gedeeltelijk componentbestand.'}
        $link=$item.PSObject.Properties['LinkType']
        if($link -and $link.Value -eq 'HardLink'){throw 'Gedeeltelijk componentbestand is een hardlink.'}
    }
    return $partial
}

function Get-A2DownloadRange($Response,[long]$Offset) {
    $status=[int]$Response.StatusCode
    if($Response.RequestMessage.RequestUri.Scheme -ne 'https'){throw 'Componentdownload heeft geen HTTPS-verbinding.'}
    $length=if($null -eq $Response.Content.Headers.ContentLength){-1L}else{[long]$Response.Content.Headers.ContentLength}
    if($length -lt -1 -or $length -eq 0 -or $length -gt 180MB){throw 'Componentdownload heeft een ongeldige verwachte grootte.'}
    if($status -eq 200){return @{offset=0L;length=$length}}
    if($status -ne 206){throw 'Onverwacht antwoord op componentdownload.'}
    $range=$Response.Content.Headers.ContentRange
    if($null -eq $range -or $range.Unit -ne 'bytes' -or -not $range.HasRange -or -not $range.HasLength -or
            $range.From -ne $Offset -or $range.Length -le $Offset -or $range.Length -gt 180MB -or
            $range.To -ne $range.Length-1 -or ($length -ge 0 -and $length -ne $range.Length-$Offset)){
        throw 'Server gaf een ongeldig hervatbereik; er is niets toegevoegd.'
    }
    return @{offset=$Offset;length=[long]$range.Length}
}

function Copy-A2ProviderStream($InputStream,[string]$Destination,[string]$Pin,
        [long]$ExpectedLength=-1,[string]$Component=([IO.Path]::GetFileName($Destination)),
        [double]$DeadlineMilliseconds=0,[scriptblock]$Clock={Get-A2DownloadMilliseconds},
        [scriptblock]$Progress={param($name,$received,$expected) Write-A2DownloadProgress $name $received $expected},
        [Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None,
        [string]$ProgressRoot,[string]$ProgressPath,[long]$ResumeOffset=-1) {
    if($ExpectedLength -lt -1 -or $ExpectedLength -eq 0 -or $ExpectedLength -gt 180MB){throw 'Componentdownload heeft een ongeldige verwachte grootte.'}
    if($DeadlineMilliseconds -eq 0){$DeadlineMilliseconds=(& $Clock)+600000}
    Assert-A2PublicPath $Destination
    $folder=Split-Path -Parent $Destination
    [IO.Directory]::CreateDirectory($folder) | Out-Null
    $temporary=if($ResumeOffset -ge 0){Get-A2DownloadPartial $Destination $Pin}else{Join-Path $folder ('.'+[IO.Path]::GetFileName($Destination)+'-'+[Guid]::NewGuid().ToString('N')+'.download')}
    Assert-A2PublicPath $temporary
    $output=$null;$keepPartial=($ResumeOffset -ge 0)
    try{
        if($ResumeOffset -ge 0){
            if($ResumeOffset -gt 180MB -or ($ExpectedLength -ge 0 -and $ResumeOffset -gt $ExpectedLength)){throw 'Ongeldige hervatpositie.'}
            $mode=if($ResumeOffset -eq 0){[IO.FileMode]::Create}else{[IO.FileMode]::Open}
            $output=[IO.File]::Open($temporary,$mode,[IO.FileAccess]::Write,[IO.FileShare]::None)
            if($output.Length -ne $ResumeOffset){throw 'Gedeeltelijke download veranderde; hervatten gestopt.'}
            $null=$output.Seek($ResumeOffset,[IO.SeekOrigin]::Begin)
            $keepPartial=$true
        }else{$output=[IO.File]::Open($temporary,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)}
        $buffer=New-Object byte[] 65536;$total=[Math]::Max(0L,$ResumeOffset)
        $lastProgress=(& $Clock);$lastProgressBytes=0L
        $null=& $Progress $Component $total $ExpectedLength
        Write-A2ComponentState $ProgressRoot $ProgressPath 'downloading' $Component $total $ExpectedLength
        while($true){
            if((& $Clock) -ge $DeadlineMilliseconds){throw ('Downloadtijd verstreken voor '+$Component+'; probeer later opnieuw.')}
            $read=$InputStream.ReadAsync($buffer,0,$buffer.Length,$CancellationToken)
            Wait-A2DownloadTask $read $DeadlineMilliseconds $Clock $Component
            $count=$read.GetAwaiter().GetResult()
            if($count -eq 0){break}
            $total+=$count
            if($total -gt 180MB){$keepPartial=$false;throw 'Componentdownload is te groot; niets uitgepakt.'}
            if($ExpectedLength -ge 0 -and $total -gt $ExpectedLength){$keepPartial=$false;throw ('Componentdownload is langer dan aangekondigd: '+$Component+'. Niets uitgepakt.')}
            $output.Write($buffer,0,$count)
            $now=(& $Clock)
            if($now-$lastProgress -ge 1000 -or $total-$lastProgressBytes -ge 1MB){
                $null=& $Progress $Component $total $ExpectedLength
                Write-A2ComponentState $ProgressRoot $ProgressPath 'downloading' $Component $total $ExpectedLength
                $lastProgress=$now;$lastProgressBytes=$total
            }
        }
        if($ExpectedLength -ge 0 -and $total -ne $ExpectedLength){throw ('Componentdownload is onvolledig: '+$Component+'. Probeer later opnieuw.')}
        $null=& $Progress $Component $total $ExpectedLength
        Write-A2ComponentState $ProgressRoot $ProgressPath 'downloading' $Component $total $ExpectedLength
        $output.Dispose();$output=$null
        $keepPartial=$false
        $null=Test-A2ProviderFile $temporary $Pin
        if([IO.File]::Exists($Destination)){$null=Test-A2ProviderFile $Destination $Pin}
        else{[IO.File]::Move($temporary,$Destination)}
    }finally{
        if($output){$output.Dispose()}
        if(-not $keepPartial -and [IO.File]::Exists($temporary)){
            if([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($temporary)) -ne [IO.Path]::GetFullPath($folder)){throw 'Onverwacht tijdelijk pad; opruimen gestopt.'}
            [IO.File]::Delete($temporary)
        }
    }
}

function Install-A2PublicProviders([string]$Root,[switch]$OfflineCheck,[string]$ProgressPath,[switch]$LauncherOnly, [switch]$SkipMedia,
        [scriptblock]$ClientFactory={New-Object Net.Http.HttpClient}) {
    Assert-A2PublicPath $Root
    if(-not [IO.Directory]::Exists($Root)){throw 'De uitgepakte launchermap ontbreekt.'}
    Add-Type -AssemblyName System.Net.Http
    $client=& $ClientFactory
    $client.Timeout=[TimeSpan]::FromMinutes(10)
    $downloaded=0;$activeComponent=''
    try{
        Write-A2ComponentState $Root $ProgressPath 'checking'
        $providers=@(Get-A2PublicProviders -LauncherOnly:$LauncherOnly -SkipMedia:$SkipMedia)
        foreach($provider in $providers){
            $activeComponent=$provider.name
            Write-A2ComponentState $Root $ProgressPath 'checking' $activeComponent
            $destination=Join-Path $Root ('payload\'+$provider.name)
            if(Test-A2ProviderFile $destination $provider.sha256){continue}
            if($OfflineCheck){throw ('Component ontbreekt: '+$provider.name+'. Open Launcher.cmd met internetverbinding voor de eerste voorbereiding.')}
            Write-Host ('Component voorbereiden: '+$provider.name)
            $response=$null;$stream=$null;$requestMessage=$null;$cancel=New-Object Threading.CancellationTokenSource
            $partial=Get-A2DownloadPartial $destination $provider.sha256
            $offset=if([IO.File]::Exists($partial)){(Get-Item -LiteralPath $partial).Length}else{0L}
            try{
                # ResponseHeadersRead ends HttpClient's body timeout. Keep one
                # monotonic budget and cancellation token for headers AND body.
                $deadline=(Get-A2DownloadMilliseconds)+600000
                $cancel.CancelAfter(600000)
                $requestMessage=New-Object Net.Http.HttpRequestMessage ([Net.Http.HttpMethod]::Get),$provider.url
                if($offset -gt 0){$requestMessage.Headers.Range=New-Object Net.Http.Headers.RangeHeaderValue $offset,$null}
                $request=$client.SendAsync($requestMessage,[Net.Http.HttpCompletionOption]::ResponseHeadersRead,$cancel.Token)
                Wait-A2DownloadTask $request $deadline {Get-A2DownloadMilliseconds} $provider.name
                $response=$request.GetAwaiter().GetResult()
                if($response.RequestMessage.RequestUri.Scheme -ne 'https'){throw 'Componentdownload heeft geen HTTPS-verbinding.'}
                if([int]$response.StatusCode -eq 416 -and $offset -gt 0){
                    # A completed body may have been interrupted before promotion.
                    try{$null=Test-A2ProviderFile $partial $provider.sha256}
                    catch{[IO.File]::Delete($partial);throw 'Server kan deze download niet hervatten. Probeer opnieuw vanaf het begin.'}
                    [IO.File]::Move($partial,$destination);$downloaded++;continue
                }
                $response.EnsureSuccessStatusCode() | Out-Null
                $range=Get-A2DownloadRange $response $offset
                $opening=$response.Content.ReadAsStreamAsync()
                Wait-A2DownloadTask $opening $deadline {Get-A2DownloadMilliseconds} $provider.name
                $stream=$opening.GetAwaiter().GetResult()
                Copy-A2ProviderStream $stream $destination $provider.sha256 -ExpectedLength $range.length -ResumeOffset $range.offset -Component $provider.name -DeadlineMilliseconds $deadline -CancellationToken $cancel.Token -ProgressRoot $Root -ProgressPath $ProgressPath
                $downloaded++
            }finally{$cancel.Cancel();if($stream){$stream.Dispose()};if($response){$response.Dispose()};if($requestMessage){$requestMessage.Dispose()};$cancel.Dispose()}
        }
        Write-A2ComponentState $Root $ProgressPath 'complete'
    }catch{
        Write-A2ComponentState $Root $ProgressPath 'error' $activeComponent
        throw
    }finally{$client.Dispose()}
    return @{components_downloaded=$downloaded;components_checked=$providers.Count;game_downloaded=$false;
             scope=if($LauncherOnly){'launcher'}else{'game'}}
}

try {Install-A2PublicProviders $KitPath -OfflineCheck:$CheckOnly -ProgressPath $ProgressPath -LauncherOnly:$LauncherOnly -SkipMedia:$SkipMedia | ConvertTo-Json -Compress}
catch {Write-Error $_.Exception.Message;exit 1}
