#Requires -Version 5.1
param(
    [string]$PythonPath,
    [ValidateSet('a2racer1','a2racer2')][string]$Game = 'a2racer1',
    [switch]$CheckOnly,
    [string]$PreviewPath,
    [string]$PreviewCatalogPath,
    [string]$PreviewReportPath,
    [string]$PreviewComparisonPath,
    [ValidateSet('summary','timeline','logs','comparison')][string]$PreviewPage = 'summary'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'launcher_common.ps1')
$workspacePath = Split-Path -Parent $PSScriptRoot
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
$script:operation = $null; $script:binding = $false; $script:game = $Game
$script:catalogWarnings = @(); $script:outputLimit = 2097152

function Get-DevtoolsProperty($Object, [string]$Name, $Default = $null) {
    if ($null -eq $Object) { return $Default }
    if ($Object -is [Collections.IDictionary]) {
        if ($Object.Contains($Name)) { return $Object[$Name] }
    } else {
        $property = $Object.PSObject.Properties[$Name]
        if ($property) { return $property.Value }
    }
    return $Default
}

function Set-DevtoolsStatus([string]$Title, [string]$Message) {
    $ui.StatusTitle.Text = $Title; $ui.StatusMessage.ToolTip = $Message
    $singleLine = ($Message -replace '[\r\n]+',' ').Trim()
    $ui.StatusMessage.Text = if ($singleLine.Length -gt 240) { $singleLine.Substring(0,237) + '…' } else { $singleLine }
}

function Format-DevtoolsValue($Value) {
    if ($null -eq $Value) { return 'onbekend / niet vastgelegd' }
    if ($Value -is [string]) { return $Value }
    return ($Value | ConvertTo-Json -Depth 20)
}

function Format-DevtoolsSection([string]$Title, $Value) {
    return $Title + "`r`n" + (Format-DevtoolsValue $Value) + "`r`n"
}

function Get-DevtoolsChoice($Control) {
    if ($Control.SelectedItem) { return [string]$Control.SelectedItem.Tag }
    return ''
}

function Add-DevtoolsChoice($Control, [string]$Label, [string]$Value) {
    $item = New-Object Windows.Controls.ComboBoxItem
    $item.Content = $Label; $item.Tag = $Value; $item.ToolTip = $Label
    $null = $Control.Items.Add($item)
}

function Update-DevtoolsButtons {
    $idle = $null -eq $script:operation
    $run = Get-DevtoolsChoice $ui.RunChoice; $other = Get-DevtoolsChoice $ui.OtherRunChoice
    foreach ($name in @('GameChoice','RunChoice','OtherRunChoice','RefreshButton')) { $ui[$name].IsEnabled = $idle }
    $ui.SearchButton.IsEnabled = [bool]($idle -and $run)
    $ui.CompareButton.IsEnabled = [bool]($idle -and $run -and $other -and $run -ne $other)
}

function Clear-DevtoolsReport {
    $ui.SummaryText.Text = 'Kies een opgeslagen proef. Er wordt geen nieuwe speelproef uitgevoerd.'
    $ui.TimelineText.Text = 'Nog geen tijdlijn geladen.'
    $ui.LogsText.Text = 'Nog geen logs geladen.'
    $ui.CompareText.Text = 'Kies twee verschillende proeven van dezelfde game en klik op Vergelijken.'
}

function Set-DevtoolsCatalog($Data) {
    $oldRun = Get-DevtoolsChoice $ui.RunChoice; $oldOther = Get-DevtoolsChoice $ui.OtherRunChoice
    $script:catalogWarnings = @(Get-DevtoolsProperty $Data 'warnings' @())
    $script:binding = $true
    try {
        $ui.RunChoice.Items.Clear(); $ui.OtherRunChoice.Items.Clear()
        foreach ($entry in @(Get-DevtoolsProperty $Data 'runs' @())) {
            if ((Get-DevtoolsProperty $entry 'game' '') -ne $script:game) { continue }
            $run = [string](Get-DevtoolsProperty $entry 'run' '')
            if (-not $run) { continue }
            $profile = [string](Get-DevtoolsProperty $entry 'profile' '')
            $label = $run + $(if ($profile) { ' · ' + $profile } else { '' })
            Add-DevtoolsChoice $ui.RunChoice $label $run
            Add-DevtoolsChoice $ui.OtherRunChoice $label $run
        }
        if ($ui.RunChoice.Items.Count) {
            $ui.RunChoice.SelectedIndex = 0
            foreach ($item in $ui.RunChoice.Items) { if ($item.Tag -eq $oldRun) { $ui.RunChoice.SelectedItem = $item } }
            $ui.OtherRunChoice.SelectedIndex = if ($ui.OtherRunChoice.Items.Count -gt 1) { 1 } else { 0 }
            foreach ($item in $ui.OtherRunChoice.Items) { if ($item.Tag -eq $oldOther) { $ui.OtherRunChoice.SelectedItem = $item } }
        }
    } finally { $script:binding = $false }
    Clear-DevtoolsReport
    if (-not $ui.RunChoice.Items.Count) {
        $message = 'Voor deze game staan nog geen leesbare proefrapporten klaar.'
        if ($script:catalogWarnings.Count) { $message += ' ' + ($script:catalogWarnings -join ' ') }
        Set-DevtoolsStatus 'Geen opgeslagen proeven' $message
    }
    Update-DevtoolsButtons
}

function Set-DevtoolsReport($Data) {
    $summary = @(
        'PROEF: ' + [string](Get-DevtoolsProperty $Data 'run' '')
        'GAME: ' + [string](Get-DevtoolsProperty $Data 'game' '')
        ''
        (Format-DevtoolsSection 'Samenvatting' (Get-DevtoolsProperty $Data 'summary'))
        (Format-DevtoolsSection 'Instellingen' (Get-DevtoolsProperty $Data 'configuration'))
        (Format-DevtoolsSection 'Bronintegriteit' (Get-DevtoolsProperty $Data 'integrity'))
        (Format-DevtoolsSection 'Waargenomen modules' (Get-DevtoolsProperty $Data 'modules'))
        'LEESGRENS: proces- en vensterwaarnemingen zijn momentopnamen. Een geladen module bewijst geen gebruikte API of geslaagde compatibiliteit. Ontbrekende gegevens blijven onbekend.'
        ''
        (Format-DevtoolsSection 'Beperkingen van dit rapport' (Get-DevtoolsProperty $Data 'limits'))
    )
    $warnings = @($script:catalogWarnings) + @(Get-DevtoolsProperty $Data 'warnings' @())
    if ($warnings.Count) { $summary += Format-DevtoolsSection 'Meldingen' $warnings }
    $ui.SummaryText.Text = $summary -join "`r`n"
    $timeline = New-Object Text.StringBuilder
    foreach ($entry in @(Get-DevtoolsProperty $Data 'timeline' @())) {
        $prefix = '[' + [string](Get-DevtoolsProperty $entry 'source' '?') + ':' + [string](Get-DevtoolsProperty $entry 'line' '?') + '] '
        $time = [string](Get-DevtoolsProperty $entry 'time' '')
        $null = $timeline.AppendLine($prefix + $time + '  ' + (Format-DevtoolsValue (Get-DevtoolsProperty $entry 'event' '')))
    }
    $ui.TimelineText.Text = if ($timeline.Length) { $timeline.ToString() } else { 'Geen passende tijdlijnregels vastgelegd.' }
    $logs = New-Object Text.StringBuilder
    foreach ($entry in @(Get-DevtoolsProperty $Data 'logs' @())) {
        $prefix = '[' + [string](Get-DevtoolsProperty $entry 'source' '?') + ':' + [string](Get-DevtoolsProperty $entry 'line' '?') + '] '
        $null = $logs.AppendLine($prefix + [string](Get-DevtoolsProperty $entry 'text' ''))
    }
    $ui.LogsText.Text = if ($logs.Length) { $logs.ToString() } else { 'Geen passende logregels vastgelegd.' }
    $query = $ui.QueryText.Text
    $message = if ($query) { 'Tijdlijn en logs gefilterd op: ' + $query } else { 'Samenvatting, tijdlijn en logs uit bestaande rapporten geladen.' }
    if ($warnings.Count) { $message += ' Er zijn meldingen; zie Samenvatting.' }
    Set-DevtoolsStatus 'Rapport geladen' $message
}

function Set-DevtoolsComparison($Data) {
    $lines = @('VERGELIJKING: ' + [string](Get-DevtoolsProperty $Data 'run' '') + ' ↔ ' + [string](Get-DevtoolsProperty $Data 'other_run' ''), '')
    $changes = @(Get-DevtoolsProperty $Data 'changes' @())
    if ($changes.Count) {
        foreach ($change in $changes) {
            $lines += [string](Get-DevtoolsProperty $change 'field' '?')
            $lines += '  Links: ' + (Format-DevtoolsValue (Get-DevtoolsProperty $change 'left'))
            $lines += '  Rechts: ' + (Format-DevtoolsValue (Get-DevtoolsProperty $change 'right'))
            $lines += ''
        }
    } else { $lines += 'Geen verschillen gevonden in de vastgelegde vergelijkingsvelden. Ontbrekende gegevens zijn geen bewijs dat twee proeven gelijk waren.' }
    foreach ($field in @('left_summary','right_summary')) {
        $value = Get-DevtoolsProperty $Data $field
        if ($null -ne $value) { $lines += Format-DevtoolsSection $(if ($field -eq 'left_summary') { 'Binary- en proefgegevens links' } else { 'Binary- en proefgegevens rechts' }) $value }
    }
    $warnings = @(Get-DevtoolsProperty $Data 'warnings' @())
    if ($warnings.Count) { $lines += Format-DevtoolsSection 'Meldingen' $warnings }
    $lines += 'Deze vergelijking leest opgeslagen waarnemingen en verandert geen instellingen.'
    $ui.CompareText.Text = $lines -join "`r`n"
    $ui.Pages.SelectedIndex = 3
    Set-DevtoolsStatus 'Vergelijking geladen' ('Verschillende vastgelegde velden: ' + $changes.Count + $(if ($warnings.Count) { '. Er zijn meldingen; zie Vergelijking.' } else { '.' }))
}

function Get-DevtoolsPython {
    if (-not $script:PythonPath) {
        $config = Join-Path $workspacePath 'local\launcher\runtimes.json'
        Assert-LauncherPath $config
        if (Test-Path -LiteralPath $config -PathType Leaf) {
            if ((Get-Item -LiteralPath $config).Length -gt 4096) { throw 'Runtimeconfig is te groot.' }
            $runtime = [IO.File]::ReadAllText($config) | ConvertFrom-Json
            $script:PythonPath = [string](Get-DevtoolsProperty $runtime 'python_path' '')
        }
    }
    if (-not $script:PythonPath) { $script:PythonPath = Join-Path $workspacePath 'local\portable-runtime\python\python.exe' }
    if (-not [IO.Path]::IsPathRooted($script:PythonPath) -or $script:PythonPath -match '(?i)[\\/]WindowsApps[\\/]') {
        throw 'Geef een bestaande Python 3-interpreter met een volledig pad.'
    }
    Assert-LauncherPath $script:PythonPath
    if (-not (Test-Path -LiteralPath $script:PythonPath -PathType Leaf)) { throw 'Python ontbreekt. Gebruik de complete portable kit of configureer de lokale runtime.' }
    return $script:PythonPath
}

function New-DevtoolsChannel($Reader) {
    $buffer = New-Object 'char[]' 4096
    return @{ reader=$Reader; buffer=$buffer; pending=$Reader.ReadAsync($buffer,0,$buffer.Length); text=(New-Object Text.StringBuilder); ended=$false }
}

function Read-DevtoolsChannel($Channel) {
    # Drain without blocking the UI; neither stream can grow beyond the cap.
    for ($i = 0; $i -lt 16 -and -not $Channel.ended -and $Channel.pending.IsCompleted; $i++) {
        $count = $Channel.pending.GetAwaiter().GetResult()
        if ($count -eq 0) { $Channel.ended = $true; break }
        if ($Channel.text.Length + $count -gt $script:outputLimit) { throw 'Rapportuitvoer overschrijdt de leeslimiet.' }
        $null = $Channel.text.Append($Channel.buffer,0,$count)
        $Channel.pending = $Channel.reader.ReadAsync($Channel.buffer,0,$Channel.buffer.Length)
    }
}

function Stop-DevtoolsOperation {
    if (-not $script:operation) { return }
    # Ownership is the exact Python Process object started by this viewer.
    $owned = $script:operation; $script:operation = $null
    try { if (-not $owned.process.HasExited) { $owned.process.Kill() } } catch { }
    try { $owned.process.Dispose() } catch { }
}

function Start-DevtoolsOperation([ValidateSet('list','show','compare')][string]$Kind) {
    if ($script:operation) { return }
    try {
        $python = Get-DevtoolsPython
        $backend = Join-Path $PSScriptRoot 'devtools_report.py'
        Assert-LauncherPath $backend
        if (-not (Test-Path -LiteralPath $backend -PathType Leaf)) { throw 'De rapportlezer ontbreekt in deze launcher.' }
        $arguments = @('-B',$backend,$Kind,'--root',$workspacePath,'--game',$script:game)
        if ($Kind -ne 'list') {
            $run = Get-DevtoolsChoice $ui.RunChoice
            if (-not $run) { return }
            $arguments += @('--run',$run)
            if ($Kind -eq 'show' -and $ui.QueryText.Text) { $arguments += @('--query',$ui.QueryText.Text) }
        }
        if ($Kind -eq 'compare') {
            $other = Get-DevtoolsChoice $ui.OtherRunChoice
            if (-not $other -or $run -eq $other) { return }
            $arguments += @('--other-run',$other)
        }
        $info = New-Object Diagnostics.ProcessStartInfo
        $info.FileName = $python; $info.Arguments = ConvertTo-LauncherArguments $arguments
        $info.WorkingDirectory = $workspacePath; $info.UseShellExecute = $false; $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
        $info.StandardOutputEncoding = [Text.Encoding]::UTF8; $info.StandardErrorEncoding = [Text.Encoding]::UTF8
        $process = New-Object Diagnostics.Process; $process.StartInfo = $info
        try {
            if (-not $process.Start()) { throw 'Rapportlezer kon niet worden gestart.' }
            $script:operation = @{ process=$process; kind=$Kind; started=[Diagnostics.Stopwatch]::StartNew(); output=(New-DevtoolsChannel $process.StandardOutput); error=(New-DevtoolsChannel $process.StandardError) }
        } catch { try { if (-not $process.HasExited) { $process.Kill() } } catch { }; $process.Dispose(); throw }
        Update-DevtoolsButtons
        Set-DevtoolsStatus 'Rapporten lezen…' 'De opgeslagen gegevens worden op de achtergrond gelezen.'
    } catch { Set-DevtoolsStatus 'Kon rapport niet lezen' $_.Exception.Message; Update-DevtoolsButtons }
}

function Poll-DevtoolsOperation {
    if (-not $script:operation) { return }
    try {
        if ($script:operation.started.Elapsed.TotalSeconds -gt 20) { throw 'De rapportlezer duurde langer dan 20 seconden. Vernieuw om opnieuw te proberen.' }
        Read-DevtoolsChannel $script:operation.output; Read-DevtoolsChannel $script:operation.error
        if (-not $script:operation.process.HasExited -or -not $script:operation.output.ended -or -not $script:operation.error.ended) { return }
        $completed = $script:operation; $script:operation = $null
        $exitCode = $completed.process.ExitCode; $kind = $completed.kind
        $json = $completed.output.text.ToString(); $errorText = $completed.error.text.ToString()
        $completed.process.Dispose()
        if ($exitCode -ne 0) {
            if (-not $errorText -and $json) {
                try { $errorData = $json | ConvertFrom-Json; $errorText = Format-DevtoolsValue (Get-DevtoolsProperty $errorData 'error' 'De rapportlezer gaf een fout terug.') } catch { }
            }
            throw $(if ($errorText) { $errorText } else { 'De rapportlezer gaf een fout terug.' })
        }
        $data = $json | ConvertFrom-Json
        if ((Get-DevtoolsProperty $data 'schema' 0) -ne 1) { throw 'Dit rapportformaat wordt nog niet ondersteund.' }
        switch ($kind) {
            'list' { Set-DevtoolsCatalog $data; if ($ui.RunChoice.Items.Count) { Start-DevtoolsOperation 'show' } }
            'show' { Set-DevtoolsReport $data }
            'compare' { Set-DevtoolsComparison $data }
        }
        Update-DevtoolsButtons
    } catch { Stop-DevtoolsOperation; Set-DevtoolsStatus 'Kon rapport niet lezen' $_.Exception.Message; Update-DevtoolsButtons }
}

function Read-DevtoolsPreview([string]$Path) {
    $localPrefix = [IO.Path]::GetFullPath((Join-Path $workspacePath 'local')).TrimEnd('\') + '\'
    if (-not [IO.Path]::GetFullPath($Path).StartsWith($localPrefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Synthetische previewgegevens moeten onder local/ staan.' }
    Assert-LauncherPath $Path
    if ((Get-Item -LiteralPath $Path).Length -gt $script:outputLimit) { throw 'Previewrapport is te groot.' }
    $data = [IO.File]::ReadAllText($Path) | ConvertFrom-Json
    if ((Get-DevtoolsProperty $data 'schema' 0) -ne 1) { throw 'Onbekend previewrapportformaat.' }
    return $data
}

function Save-DevtoolsPreview([string]$Path) {
    # A preview can never overwrite a game, runtime or saved trial report.
    $previewRoot = [IO.Path]::GetFullPath((Join-Path $workspacePath 'local\devtools\qa')).TrimEnd('\') + '\'
    $absolutePath = [IO.Path]::GetFullPath($Path)
    if (-not $absolutePath.StartsWith($previewRoot,[StringComparison]::OrdinalIgnoreCase) -or
        -not [IO.Path]::GetExtension($absolutePath).Equals('.png',[StringComparison]::OrdinalIgnoreCase)) {
        throw 'Preview moet een PNG onder local/devtools/qa/ zijn.'
    }
    Assert-LauncherPath $Path
    $content = $window.Content; $window.Content = $null
    $surface = New-Object Windows.Controls.Border; $surface.Background = $window.Background; $surface.Child = $content; $surface.Resources = $window.Resources
    [Windows.Documents.TextElement]::SetForeground($surface,$window.Foreground)
    [Windows.Documents.TextElement]::SetFontFamily($surface,$window.FontFamily)
    [Windows.Documents.TextElement]::SetFontSize($surface,$window.FontSize)
    $width = [int]$window.Width; $height = [int]$window.Height
    $surface.Measure((New-Object Windows.Size $width,$height)); $surface.Arrange((New-Object Windows.Rect 0,0,$width,$height)); $surface.UpdateLayout()
    $bitmap = New-Object Windows.Media.Imaging.RenderTargetBitmap $width,$height,96,96,([Windows.Media.PixelFormats]::Pbgra32)
    $bitmap.Render($surface)
    $encoder = New-Object Windows.Media.Imaging.PngBitmapEncoder; $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
    $null = [IO.Directory]::CreateDirectory((Split-Path -Parent $Path))
    $stream = [IO.File]::Open($Path,[IO.FileMode]::Create,[IO.FileAccess]::Write)
    try { $encoder.Save($stream) } finally { $stream.Dispose() }
}

try {
    Assert-LauncherPath $workspacePath
    $xamlPath = Join-Path $PSScriptRoot 'devtools_window.xaml'; Assert-LauncherPath $xamlPath
    $reader = New-Object Xml.XmlNodeReader ([xml][IO.File]::ReadAllText($xamlPath))
    try { $window = [Windows.Markup.XamlReader]::Load($reader) } finally { $reader.Close() }
    $ui = @{}
    foreach ($name in @('GameChoice','RunChoice','OtherRunChoice','RefreshButton','QueryText','SearchButton','CompareButton','Pages','SummaryText','TimelineText','LogsText','CompareText','StatusTitle','StatusMessage')) {
        $ui[$name] = $window.FindName($name)
        if (-not $ui[$name]) { throw ('Ontbrekend devtoolselement: ' + $name) }
    }
    Add-DevtoolsChoice $ui.GameChoice 'A2 Racer I' 'a2racer1'; Add-DevtoolsChoice $ui.GameChoice 'A2 Racer II' 'a2racer2'
    $ui.GameChoice.SelectedIndex = if ($Game -eq 'a2racer2') { 1 } else { 0 }
    Clear-DevtoolsReport; Update-DevtoolsButtons
    if ($CheckOnly -or $PreviewPath) {
        if ($PreviewCatalogPath) { Set-DevtoolsCatalog (Read-DevtoolsPreview $PreviewCatalogPath) }
        if ($PreviewReportPath) { Set-DevtoolsReport (Read-DevtoolsPreview $PreviewReportPath) }
        if ($PreviewComparisonPath) { Set-DevtoolsComparison (Read-DevtoolsPreview $PreviewComparisonPath) }
        $ui.Pages.SelectedIndex = @{ summary=0; timeline=1; logs=2; comparison=3 }[$PreviewPage]
        if ($PreviewPath) { Save-DevtoolsPreview $PreviewPath }
        Write-Output 'Devtoolscontrole geslaagd: WPF en alle rapportvelden geladen; geen game gestart, proces onderzocht of rapportlezer uitgevoerd.'
        return
    }
    if ($PreviewCatalogPath -or $PreviewReportPath -or $PreviewComparisonPath) { throw 'Previewgegevens kunnen alleen samen met -CheckOnly of -PreviewPath worden gebruikt.' }
    $ui.RefreshButton.Add_Click({ Start-DevtoolsOperation 'list' })
    $ui.GameChoice.Add_SelectionChanged({
        if (-not $script:binding -and -not $script:operation) {
            $script:game = Get-DevtoolsChoice $ui.GameChoice
            $script:binding = $true
            try { $ui.RunChoice.Items.Clear(); $ui.OtherRunChoice.Items.Clear() } finally { $script:binding = $false }
            Clear-DevtoolsReport; Start-DevtoolsOperation 'list'
        }
    })
    $ui.RunChoice.Add_SelectionChanged({ if (-not $script:binding) { $ui.CompareText.Text = 'Kies een tweede proef en klik op Vergelijken.'; Start-DevtoolsOperation 'show' } })
    $ui.OtherRunChoice.Add_SelectionChanged({ if (-not $script:binding) { $ui.CompareText.Text = 'Klik op Vergelijken om deze twee proeven naast elkaar te zetten.'; Update-DevtoolsButtons } })
    $ui.SearchButton.Add_Click({ Start-DevtoolsOperation 'show' })
    $ui.QueryText.Add_KeyDown({ if ($_.Key -eq [Windows.Input.Key]::Return) { Start-DevtoolsOperation 'show'; $_.Handled = $true } })
    $ui.CompareButton.Add_Click({ Start-DevtoolsOperation 'compare' })
    $timer = New-Object Windows.Threading.DispatcherTimer
    $timer.Interval = [TimeSpan]::FromMilliseconds(100); $timer.Add_Tick({ Poll-DevtoolsOperation })
    $window.Add_Loaded({ $timer.Start(); Start-DevtoolsOperation 'list' })
    $window.Add_Closed({ $timer.Stop(); Stop-DevtoolsOperation })
    $null = $window.ShowDialog()
} catch {
    if ($CheckOnly -or $PreviewPath) { Write-Error $_.Exception.Message; exit 1 }
    $null = [Windows.MessageBox]::Show($_.Exception.Message,'A2 Revival — Devtools','OK','Error')
    exit 1
}
