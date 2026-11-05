# Background update controls. Dot-sourcing has no network or installer side effects.
function Initialize-LauncherUpdates($Window, $Controls, [string]$Root, [scriptblock]$Runtime, [scriptblock]$Busy) {
    foreach ($name in @('LauncherVersion','CheckUpdates','OpenReleases','DownloadUpdate','InstallUpdate','AutomaticUpdates','UpdateMessage')) {
        $Controls[$name] = $Window.FindName($name)
        if (-not $Controls[$name]) { throw ('Ontbrekend update-element: ' + $name) }
    }
    $script:launcherUpdates = @{
        window=$Window; ui=$Controls; root=$Root; runtime=$Runtime; busy=$Busy;
        process=$null; action=$null; initialized=$false; binding=$false; offer=$null; receipt=$null;
        autoApply=$false; prompted=$false; receiptKind=$null
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

function Confirm-LauncherUpdate([string]$Text) {
    $answer = [Windows.MessageBox]::Show($script:launcherUpdates.window, $Text, 'A2 Racers Revival bijwerken', 'YesNo', 'Question')
    return ($answer -eq [Windows.MessageBoxResult]::Yes)
}

function Show-LauncherUpdateNotice([string]$Text, [bool]$Failed) {
    $icon = if ($Failed) {'Warning'} else {'Information'}
    $null = [Windows.MessageBox]::Show($script:launcherUpdates.window, $Text, 'A2 Racers Revival', 'OK', $icon)
}

function Test-LauncherBatchHost([string]$CommandLine) {
    # Only a cmd that was started just to run Launcher.cmd (double-click or the
    # updater restart: cmd /c ...Launcher.cmd) closes after the launcher. An
    # interactive cmd (no /c, or /k) stays open, so the updater must not wait on it.
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    return [bool]($CommandLine -match '(?i)(^|\s)/c(\s|"|$)' -and $CommandLine -notmatch '(?i)(^|\s)/k(\s|"|$)' -and
        $CommandLine -match '(?i)launcher\.cmd')
}

function Get-LauncherParentShell {
    # Launcher.cmd waits for this PowerShell; the updater waits for both before
    # it replaces Launcher.cmd itself, unless the cmd window stays open anyway.
    try {
        $parentId = [int](Get-CimInstance Win32_Process -Filter ('ProcessId=' + $PID) -ErrorAction Stop).ParentProcessId
        $parent = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $parentId) -ErrorAction Stop
        if ($parent.Name -eq 'cmd.exe' -and (Test-LauncherBatchHost ([string]$parent.CommandLine))) { return $parentId }
    } catch { }
    return $null
}

function Start-PortableLauncherUpdate($Result) {
    $state = $script:launcherUpdates
    if (& $state.busy) { $state.ui.UpdateMessage.Text = 'Sluit eerst je game of voorbereiding; daarna kun je bijwerken.'; $state.autoApply = $false; return }
    if (-not $state.autoApply) {
        $text = 'Nu bijwerken naar versie ' + $Result.version + "?`n`nDe launcher sluit even en start daarna vanzelf opnieuw. Je saves, instellingen en games blijven staan."
        if (-not (Confirm-LauncherUpdate $text)) { $state.ui.UpdateMessage.Text = 'Update staat klaar. Klik later op Nu bijwerken.'; return }
    }
    $state.autoApply = $false
    if (& $state.busy) { $state.ui.UpdateMessage.Text = 'Er is net een game of voorbereiding gestart; de update wacht.'; return }
    $runtime = & $state.runtime
    $scriptPath = Join-Path (Join-Path $state.root 'tools') 'launcher_updates.py'
    Assert-LauncherPath $scriptPath
    $arguments = @('-B', $scriptPath, '--root', $state.root, 'apply', '--receipt', [string]$Result.receipt, '--restart', '--wait', [string]$PID)
    $shell = Get-LauncherParentShell
    if ($shell) { $arguments += @('--wait', [string]$shell) }
    # The updater waits until this launcher has closed, replaces only listed
    # app files, restores them on any failure and then reopens Launcher.cmd.
    $null = New-LauncherProcess $runtime $arguments -Detached
    $state.window.Close()
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

function Get-LauncherUpdateValue($Object, [string]$Name) {
    # Older backends and MSI offers have no 'kind'; StrictMode forbids missing properties.
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($property) { return $property.Value }
    return $null
}

function Poll-LauncherUpdates {
    $state = $script:launcherUpdates
    if (-not $state.initialized -and -not $state.process) {
        $runtime = & $state.runtime
        # First show the outcome of a portable update that just ran, then settings.
        if ($runtime) { $state.initialized = $true; Start-LauncherUpdateTask 'notice' @('notice') }
    }
    $task = $state.process
    if ($task -and $task.process.HasExited) {
        $state.process = $null
        $action = $state.action
        try {
            $text = $task.output.GetAwaiter().GetResult()
            $result = $text | ConvertFrom-Json
            if ($task.process.ExitCode -ne 0 -or $result.state -eq 'error') { throw [string]$result.message }
            if ($result.state -in @('notice','none')) {
                if ($result.state -eq 'notice') {
                    $state.ui.UpdateMessage.Text = [string]$result.message
                    Show-LauncherUpdateNotice ([string]$result.message) ([string]$result.outcome -eq 'failed')
                }
            } elseif ($result.state -eq 'settings') {
                $state.binding = $true
                try { $state.ui.AutomaticUpdates.IsChecked = [bool]$result.automatic_check }
                finally { $state.binding = $false }
                $state.ui.UpdateMessage.Text = if ($result.automatic_check) {'Automatische controle staat aan.'} else {'Automatische controle staat uit. Handmatig controleren kan altijd.'}
                if ($action -in @('settings','settings-save') -and $result.automatic_check) { Start-LauncherUpdateTask 'auto-check' @('check','--automatic') }
            } else {
                $state.ui.UpdateMessage.Text = [string]$result.message
                if ($result.state -eq 'available') {
                    $state.receipt = $null
                    $state.ui.InstallUpdate.Visibility = 'Collapsed'
                    $state.offer = $result.offer
                    $state.ui.DownloadUpdate.Content = 'Download ' + $result.offer.version
                    $state.ui.DownloadUpdate.Visibility = 'Visible'
                    $portable = (Get-LauncherUpdateValue $result.offer 'kind') -eq 'portable'
                    if ($portable -and $action -eq 'auto-check' -and -not $state.prompted) {
                        # Ask once per launcher session; 'Nee' keeps the buttons on Support.
                        $state.prompted = $true
                        $current = [string](Get-LauncherUpdateValue $result 'current_version')
                        $question = 'Er is een nieuwe versie van A2 Racers Revival: ' + $result.offer.version +
                            $(if ($current) { ' (jij hebt ' + $current + ').' } else { '.' }) +
                            "`n`nNu bijwerken? De launcher downloadt en controleert de update, sluit even en start daarna vanzelf opnieuw. Je saves, instellingen en games blijven staan."
                        if (Confirm-LauncherUpdate $question) {
                            $state.autoApply = $true
                            Start-LauncherUpdateTask 'download' @('download','--version',[string]$result.offer.version)
                        } else { $state.ui.UpdateMessage.Text = 'Versie ' + $result.offer.version + ' is beschikbaar. Bijwerken kan via Support.' }
                    }
                } elseif ($result.state -eq 'downloaded') {
                    $state.receipt = [string]$result.receipt
                    $state.receiptKind = Get-LauncherUpdateValue $result 'kind'
                    $state.ui.InstallUpdate.Content = if ($state.receiptKind -eq 'portable') {'Nu bijwerken'} else {'Update installeren'}
                    $state.ui.InstallUpdate.Visibility = 'Visible'
                    if ($state.receiptKind -eq 'portable') {
                        if ($state.autoApply -or $action -eq 'verify') { Start-PortableLauncherUpdate $result }
                    } elseif ($action -eq 'verify') { Open-VerifiedLauncherUpdate $result }
                } elseif ($result.state -eq 'current') {
                    $state.offer = $null
                    $state.receipt = $null
                    $state.ui.DownloadUpdate.Visibility = 'Collapsed'
                    $state.ui.InstallUpdate.Visibility = 'Collapsed'
                }
            }
        } catch {
            $state.autoApply = $false
            $state.ui.UpdateMessage.Text = 'Update niet uitgevoerd: ' + $_.Exception.Message
        }
        finally { $task.process.Dispose() }
        # A missing or unreadable notice never blocks the normal settings/check route.
        if ($action -eq 'notice' -and -not $state.process) { Start-LauncherUpdateTask 'settings' @('settings') }
    }
    $idle = -not $state.process
    $state.ui.CheckUpdates.IsEnabled = $idle
    $state.ui.AutomaticUpdates.IsEnabled = $idle
    $state.ui.DownloadUpdate.IsEnabled = [bool]($idle -and $state.offer)
    $state.ui.InstallUpdate.IsEnabled = [bool]($idle -and $state.receipt -and -not (& $state.busy))
}
