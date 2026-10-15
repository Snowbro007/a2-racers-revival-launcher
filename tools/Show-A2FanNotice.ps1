#Requires -Version 7.0
param([ValidateSet('a2racer1','a2racer2')][string]$Game = 'a2racer1',
      [switch]$CheckOnly, [string]$PreviewPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'fan_notice_common.ps1')

try {
    Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
    $reader = [Xml.XmlNodeReader]::new([xml][IO.File]::ReadAllText((Join-Path $PSScriptRoot 'fan_notice_window.xaml')))
    try { $window = [Windows.Markup.XamlReader]::Load($reader) } finally { $reader.Close() }
    $ui = @{}
    foreach ($name in @('A2Badge','NoticeTitle','NoticeBody','OriginalCredit','RightsFooter','SourceNote','CountdownNote','ContinueButton')) {
        $ui[$name] = $window.FindName($name)
        if (-not $ui[$name]) { throw ('Fanprojectmelding mist een UI-element: ' + $name) }
    }
    $text = Get-A2FanNoticeText -Game $Game
    $ui.NoticeTitle.Text = $text.title
    $ui.NoticeBody.Text = $text.body
    $ui.OriginalCredit.Text = $text.credit
    $ui.RightsFooter.Text = $text.rights
    $ui.SourceNote.Text = $text.source
    $ui.CountdownNote.Text = 'Je gaat automatisch verder na ' + $text.seconds + ' seconden.'

    # This branch never creates a timer, registers actions or displays a window.
    if ($CheckOnly -or $PreviewPath) {
        $content = $window.Content; $window.Content = $null
        $surface = [Windows.Controls.Border]::new()
        $surface.Background = $window.Background; $surface.Resources = $window.Resources; $surface.Child = $content
        [Windows.Documents.TextElement]::SetForeground($surface, $window.Foreground)
        [Windows.Documents.TextElement]::SetFontFamily($surface, $window.FontFamily)
        [Windows.Documents.TextElement]::SetFontSize($surface, $window.FontSize)
        $width = [int]$window.Width; $height = [int]$window.Height
        $surface.Measure([Windows.Size]::new($width,$height))
        $surface.Arrange([Windows.Rect]::new(0,0,$width,$height)); $surface.UpdateLayout()
        $bounds = @{}
        foreach ($name in @('NoticeTitle','NoticeBody','OriginalCredit','RightsFooter','SourceNote','CountdownNote','ContinueButton')) {
            $control = $ui[$name]
            $point = $control.TranslatePoint([Windows.Point]::new(0,0),$surface)
            $bounds[$name] = @{x=$point.X;y=$point.Y;width=$control.ActualWidth;height=$control.ActualHeight}
            if ($control.ActualWidth -le 0 -or $control.ActualHeight -le 0 -or $point.X -lt 0 -or $point.Y -lt 0 -or
                    $point.X + $control.ActualWidth -gt $width + 1 -or $point.Y + $control.ActualHeight -gt $height + 1) {
                throw ('Fanprojectmelding bevat een onzichtbaar of afgesneden element: ' + $name)
            }
        }
        if ($ui.NoticeBody.Text -ne $text.body -or $ui.NoticeTitle.Text -ne $text.title -or
                $ui.OriginalCredit.Text -ne $text.credit -or $ui.RightsFooter.Text -ne $text.rights -or $ui.SourceNote.Text -ne $text.source) {
            throw 'De tekst van de fanprojectmelding is niet compleet.'
        }
        if ($PreviewPath) {
            $path = [IO.Path]::GetFullPath($PreviewPath)
            if ([IO.Path]::GetExtension($path) -ine '.png') { throw 'De fanprojectpreview moet een PNG-bestand zijn.' }
            $null = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))
            $bitmap = [Windows.Media.Imaging.RenderTargetBitmap]::new($width,$height,96,96,[Windows.Media.PixelFormats]::Pbgra32)
            $bitmap.Render($surface)
            $encoder = [Windows.Media.Imaging.PngBitmapEncoder]::new()
            $encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
            $stream = [IO.File]::Open($path,[IO.FileMode]::Create,[IO.FileAccess]::Write)
            try { $encoder.Save($stream) } finally { $stream.Dispose() }
        }
        @{game=$Game;title=$text.title;body=$text.body;credit=$text.credit;rights=$text.rights;source=$text.source;
            seconds=$text.seconds;width=$width;height=$height;bounds=$bounds;ui_shown=$false;timer_started=$false} |
            ConvertTo-Json -Depth 5 -Compress
        exit 0
    }

    # Window measurements are in WPF device-independent pixels.
    $work = [Windows.SystemParameters]::WorkArea
    $window.MinWidth = [Math]::Min($window.MinWidth,[Math]::Max(1,$work.Width - 24))
    $window.MinHeight = [Math]::Min($window.MinHeight,[Math]::Max(1,$work.Height - 24))
    $window.Width = [Math]::Min($window.Width,[Math]::Max(1,$work.Width - 24))
    $window.Height = [Math]::Min($window.Height,[Math]::Max(1,$work.Height - 24))
    $state = @{Completed=$false;ExitCode=2;Reason='cancel'}
    $timer = [Windows.Threading.DispatcherTimer]::new()
    $timer.Interval = [TimeSpan]::FromSeconds($text.seconds)
    function Finish-FanNotice([string]$Reason) {
        if (Set-A2FanNoticeResult -State $state -Reason $Reason) {
            $timer.Stop()
            $window.Close()
        }
    }
    $ui.ContinueButton.Add_Click({ Finish-FanNotice 'continue' })
    $timer.Add_Tick({ Finish-FanNotice 'timer' })
    $window.Add_PreviewKeyDown({
        param($sender,$event)
        if ($event.Key -eq [Windows.Input.Key]::Escape) {
            $event.Handled = $true
            Finish-FanNotice 'cancel'
        }
    })
    $window.Add_Closing({
        $null = Set-A2FanNoticeResult -State $state -Reason 'cancel'
        $timer.Stop()
    })
    $window.Add_ContentRendered({ $null = $ui.ContinueButton.Focus(); $timer.Start() })
    $null = $window.ShowDialog()
    exit ([int]$state.ExitCode)
} catch {
    [Console]::Error.WriteLine('De fanprojectmelding kon niet worden getoond: ' + $_.Exception.Message)
    exit 1
}
