#Requires -Version 5.1
[CmdletBinding()]
param([string]$KitPath = (Split-Path -Parent $PSScriptRoot), [switch]$CheckOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-A2PublicProviders {
    @(
        @{name='python-3.13.16-embed-amd64.zip';sha256='97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297';url='https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip'},
        @{name='PowerShell-7.6.5-win-x64.zip';sha256='32eb8f6cdce08f86e987d625a2733e54ac3e289ae7e1621b14c0b5bcec2434ea';url='https://github.com/PowerShell/PowerShell/releases/download/v7.6.5/PowerShell-7.6.5-win-x64.zip'},
        @{name='cnc-ddraw-v7.0.0.0.zip';sha256='f9640f69c2b8c012b97720ce0a9aac483989563908fc19446b9d1ba16e7239d6';url='https://github.com/FunkyFr3sh/cnc-ddraw/releases/download/v7.0.0.0/cnc-ddraw.zip'},
        @{name='dgVoodoo2_87_5.zip';sha256='5ffde6927f7355ca3fdd5d785b581256a8e6539fa13e395a891ade6ba1040850';url='https://github.com/dege-diosg/dgVoodoo2/releases/download/v2.87.5/dgVoodoo2_87_5.zip'},
        @{name='ffmpeg-9.0.2-essentials_build.zip';sha256='60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba';url='https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip'}
    )
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

function Copy-A2ProviderStream($InputStream,[string]$Destination,[string]$Pin) {
    Assert-A2PublicPath $Destination
    $folder=Split-Path -Parent $Destination
    [IO.Directory]::CreateDirectory($folder) | Out-Null
    $temporary=Join-Path $folder ('.'+[IO.Path]::GetFileName($Destination)+'-'+[Guid]::NewGuid().ToString('N')+'.download')
    Assert-A2PublicPath $temporary
    $output=$null
    try{
        $output=[IO.File]::Open($temporary,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $buffer=New-Object byte[] 65536;$total=0L
        while($true){
            $read=$InputStream.ReadAsync($buffer,0,$buffer.Length)
            if(-not $read.Wait(30000)){throw 'Componentdownload reageert niet; probeer later opnieuw.'}
            $count=$read.GetAwaiter().GetResult()
            if($count -eq 0){break}
            $total+=$count
            if($total -gt 180MB){throw 'Componentdownload is te groot; niets uitgepakt.'}
            $output.Write($buffer,0,$count)
        }
        $output.Dispose();$output=$null
        $null=Test-A2ProviderFile $temporary $Pin
        if([IO.File]::Exists($Destination)){$null=Test-A2ProviderFile $Destination $Pin}
        else{[IO.File]::Move($temporary,$Destination)}
    }finally{
        if($output){$output.Dispose()}
        if([IO.File]::Exists($temporary)){
            if([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($temporary)) -ne [IO.Path]::GetFullPath($folder)){throw 'Onverwacht tijdelijk pad; opruimen gestopt.'}
            [IO.File]::Delete($temporary)
        }
    }
}

function Install-A2PublicProviders([string]$Root,[switch]$OfflineCheck) {
    Assert-A2PublicPath $Root
    if(-not [IO.Directory]::Exists($Root)){throw 'De uitgepakte launchermap ontbreekt.'}
    Add-Type -AssemblyName System.Net.Http
    $client=New-Object Net.Http.HttpClient
    $client.Timeout=[TimeSpan]::FromMinutes(10)
    $downloaded=0
    try{
        foreach($provider in Get-A2PublicProviders){
            $destination=Join-Path $Root ('payload\'+$provider.name)
            if(Test-A2ProviderFile $destination $provider.sha256){continue}
            if($OfflineCheck){throw ('Component ontbreekt: '+$provider.name+'. Open Launcher.cmd met internetverbinding voor de eerste voorbereiding.')}
            Write-Host ('Component voorbereiden: '+$provider.name)
            $response=$null;$stream=$null
            try{
                $response=$client.GetAsync($provider.url,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
                $response.EnsureSuccessStatusCode() | Out-Null
                if($response.RequestMessage.RequestUri.Scheme -ne 'https'){throw 'Componentdownload heeft geen HTTPS-verbinding.'}
                if($response.Content.Headers.ContentLength -gt 180MB){throw 'Componentdownload is te groot.'}
                $stream=$response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                Copy-A2ProviderStream $stream $destination $provider.sha256
                $downloaded++
            }finally{if($stream){$stream.Dispose()};if($response){$response.Dispose()}}
        }
    }finally{$client.Dispose()}
    return @{components_downloaded=$downloaded;components_checked=5;game_downloaded=$false}
}

try {Install-A2PublicProviders $KitPath -OfflineCheck:$CheckOnly | ConvertTo-Json -Compress}
catch {Write-Error $_.Exception.Message;exit 1}
