# Background update controls. Dot-sourcing has no network or installer side effects.
function Initialize-LauncherUpdates($Window, $Controls, [string]$Root, [scriptblock]$Runtime, [scriptblock]$Busy) {
    foreach ($name in @('LauncherVersion','CheckUpdates','OpenReleases','DownloadUpdate','InstallUpdate','AutomaticUpdates','UpdateMessage')) {
        $Controls[$name] = $Window.FindName($name)
        if (-not $Controls[$name]) { throw ('Ontbrekend update-element: ' + $name) }
    }
    $script:launcherUpdates = @{
        window=$Window; ui=$Controls; root=$Root; runtime=$Runtime; busy=$Busy;
        process=$null; action=$null; initialized=$false; binding=$false; offer=$null; receipt=$null
    }
    $version = Join-Path $Root 'VERSION.txt'
    if (Test-Path -LiteralPath $version -PathType Leaf) {
        Assert-LauncherPath $version
        $Controls.LauncherVersion.Text = 'A2 Racers Revival · ' + [IO.File]::ReadAllText($version).Trim()
    }
    $Controls.CheckUpdates.Add_Click({ Start-LauncherUpdateTask 'check' @('check') })
    $Controls.OpenReleases.Add_Click({ $null = Start-Process -FilePath 'https://github.com/Snowbro007/a2-racers-revival-launcher/releases' })
    $Controls.DownloadUpdate.Add_Click({
        if ($script:launcherUpdates.offer) {
            Start-LauncherUpdateTask 'download' @('download','--version',[string]$script:launcherUpdates.offer.version)
        }
    })
    $Controls.InstallUpdate.Add_Click({
        if (-not (& $script:launcherUpdates.busy) -and $script:launcherUpdates.receipt) {
            Start-LauncherUpdateTask 'verify' @('verify','--receipt',[string]$script:launcherUpdates.receipt)
        }
    })
    $Controls.AutomaticUpdates.Add_Click({
        if (-not $script:launcherUpdates.binding) {
            $value = if ($script:launcherUpdates.ui.AutomaticUpdates.IsChecked) {'1'} else {'0'}
            Start-LauncherUpdateTask 'settings-save' @('settings','--set-automatic',$value)
        }
    })
    $updateTimer = New-Object Windows.Threading.DispatcherTimer
    $updateTimer.Interval = [TimeSpan]::FromMilliseconds(500)
    $updateTimer.Add_Tick({ Poll-LauncherUpdates })
    $Window.Add_Loaded({ $updateTimer.Start() }.GetNewClosure())
    $ownedState = $script:launcherUpdates
    $Window.Add_Closed({
        $updateTimer.Stop()
        # Own checker/download process only. Never touch game/worker processes.
        $task = $ownedState.process
        if ($task) {
            try { if (-not $task.process.HasExited) { $task.process.Kill() } } catch { }
            $task.process.Dispose()
        }
    }.GetNewClosure())
}

function Start-LauncherUpdateTask([string]$Action, [string[]]$Arguments) {
    $state = $script:launcherUpdates
    if ($state.process) { return }
    try {
        $runtime = & $state.runtime
        if (-not $runtime) { $state.ui.UpdateMessage.Text = 'Updatecontrole is beschikbaar na de eerste voorbereiding.'; return }
        $scriptPath = Join-Path (Join-Path $state.root 'tools') 'launcher_updates.py'
        Assert-LauncherPath $scriptPath
        $state.process = New-LauncherProcess $runtime (@('-B',$scriptPath,'--root',$state.root) + $Arguments)
        $state.action = $Action
        $state.ui.UpdateMessage.Text = if ($Action -eq 'download') {'Update downloaden en controleren…'} else {'Updategegevens controleren…'}
        $state.ui.CheckUpdates.IsEnabled = $false
        $state.ui.AutomaticUpdates.IsEnabled = $false
        $state.ui.DownloadUpdate.IsEnabled = $false
        $state.ui.InstallUpdate.IsEnabled = $false
    } catch { $state.ui.UpdateMessage.Text = 'Updatecontrole niet beschikbaar. Je kunt gewoon blijven spelen.' }
}

function Open-VerifiedLauncherUpdate($Result) {
    $state = $script:launcherUpdates
    if (& $state.busy) { $state.ui.UpdateMessage.Text = 'Sluit eerst je game of voorbereiding voordat je de update installeert.'; return }
    Assert-LauncherPath $Result.path
    $file = [IO.File]::Open($Result.path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        $hash = [Security.Cryptography.SHA256]::Create()
        try { $digest = [BitConverter]::ToString($hash.ComputeHash($file)).Replace('-','').ToLowerInvariant() }
        finally { $hash.Dispose() }
        if ($digest -cne [string]$Result.sha256) { throw 'De installer is na controle veranderd.' }
        $signature = Get-AuthenticodeSignature -LiteralPath $Result.path
        if ([string]$signature.Status -notin @('Valid','NotSigned')) { throw 'De digitale handtekening van deze installer is niet geldig.' }
        $publisher = if ($signature.Status -eq 'Valid') { 'Uitgever: ' + $signature.SignerCertificate.Subject } else { 'Deze installer is niet digitaal ondertekend. Windows kan een waarschuwing tonen.' }
        $answer = [Windows.MessageBox]::Show($state.window,
            ('Versie ' + $Result.version + " installeren?`n`n" + $publisher + "`n`nDe launcher sluit. Windows opent de gewone installer; je instellingen en games blijven staan. Start na afloop via het A2-icoon."),
            'A2 Racers Revival bijwerken','YesNo','Question')
        if ($answer -eq [Windows.MessageBoxResult]::Yes) {
            if (& $state.busy) { throw 'Een game of voorbereiding is gestart; de update is niet geopend.' }
            # Use the normal Windows MSI association. No quiet install, runas,
            # execution-policy change, unblock or SmartScreen workaround.
            $null = Start-Process -FilePath $Result.path
            $state.window.Close()
        }
    } finally { $file.Dispose() }
}

function Poll-LauncherUpdates {
    $state = $script:launcherUpdates
    if (-not $state.initialized -and -not $state.process) {
        $runtime = & $state.runtime
        if ($runtime) { $state.initialized = $true; Start-LauncherUpdateTask 'settings' @('settings') }
    }
    $task = $state.process
    if ($task -and $task.process.HasExited) {
        $state.process = $null
        try {
            $text = $task.output.GetAwaiter().GetResult()
            $result = $text | ConvertFrom-Json
            if ($task.process.ExitCode -ne 0 -or $result.state -eq 'error') { throw [string]$result.message }
            if ($result.state -eq 'settings') {
                $state.binding = $true
                try { $state.ui.AutomaticUpdates.IsChecked = [bool]$result.automatic_check }
                finally { $state.binding = $false }
                $state.ui.UpdateMessage.Text = if ($result.automatic_check) {'Automatische controle staat aan.'} else {'Automatische controle staat uit. Handmatig controleren kan altijd.'}
                if ($state.action -in @('settings','settings-save') -and $result.automatic_check) { Start-LauncherUpdateTask 'check' @('check','--automatic') }
            } else {
                $state.ui.UpdateMessage.Text = [string]$result.message
                if ($result.state -eq 'available') {
                    $state.receipt = $null
                    $state.ui.InstallUpdate.Visibility = 'Collapsed'
                    $state.offer = $result.offer
                    $state.ui.DownloadUpdate.Content = 'Download ' + $result.offer.version
                    $state.ui.DownloadUpdate.Visibility = 'Visible'
                } elseif ($result.state -eq 'downloaded') {
                    $state.receipt = [string]$result.receipt
                    $state.ui.InstallUpdate.Visibility = 'Visible'
                    if ($state.action -eq 'verify') { Open-VerifiedLauncherUpdate $result }
                } elseif ($result.state -eq 'current') {
                    $state.offer = $null
                    $state.receipt = $null
                    $state.ui.DownloadUpdate.Visibility = 'Collapsed'
                    $state.ui.InstallUpdate.Visibility = 'Collapsed'
                }
            }
        } catch { $state.ui.UpdateMessage.Text = 'Update niet uitgevoerd: ' + $_.Exception.Message }
        finally { $task.process.Dispose() }
    }
    $idle = -not $state.process
    $state.ui.CheckUpdates.IsEnabled = $idle
    $state.ui.AutomaticUpdates.IsEnabled = $idle
    $state.ui.DownloadUpdate.IsEnabled = [bool]($idle -and $state.offer)
    $state.ui.InstallUpdate.IsEnabled = [bool]($idle -and $state.receipt -and -not (& $state.busy))
}
