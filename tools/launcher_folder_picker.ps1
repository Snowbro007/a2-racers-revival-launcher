# Shared folder picker: direct path paste is available on PowerShell 5.1 and 7.
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase

function Resolve-A2FolderInput([string]$Text) {
    $value = ([string]$Text).Trim()
    if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    if ([string]::IsNullOrWhiteSpace($value)) { throw 'Plak een mappad of kies Bladeren.' }
    $drive = $value -match '^[A-Za-z]:[\\/]'
    $share = $value -match '^\\\\[^?\\/][^\\/]*\\[^\\/]+'
    if (-not ($drive -or $share)) { throw 'Gebruik een volledig mappad, bijvoorbeeld C:\Games\A2 Racer.' }
    $path = [IO.Path]::GetFullPath($value)
    if (-not [IO.Directory]::Exists($path)) { throw 'Deze map is niet gevonden. Controleer het pad of kies Bladeren.' }
    return $path
}

function New-A2FolderPickerWindow([Windows.Window]$Owner, [string]$Description) {
    [xml]$markup = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Gamemap kiezen" Width="680" MinWidth="520" SizeToContent="Height"
        ResizeMode="CanResizeWithGrip" WindowStartupLocation="CenterOwner"
        Background="#101c2b" Foreground="#eef4fc" FontFamily="Segoe UI" FontSize="14">
  <StackPanel Margin="24">
    <TextBlock x:Name="Description" TextWrapping="Wrap" Margin="0,0,0,14"/>
    <TextBlock Text="Plak het volledige pad naar je gamemap of kies Bladeren." Margin="0,0,0,8"/>
    <Grid><Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
      <TextBox x:Name="FolderPath" Height="34" Padding="7,4" VerticalContentAlignment="Center"
               AutomationProperties.Name="Pad naar je gamemap"/>
      <Button x:Name="Browse" Grid.Column="1" Content="Bladeren…" Margin="10,0,0,0" Padding="16,5"/>
    </Grid>
    <TextBlock x:Name="FolderError" Foreground="#ffe265" TextWrapping="Wrap" Margin="0,8,0,0" Visibility="Collapsed"/>
    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,20,0,0">
      <Button x:Name="Cancel" Content="Annuleren" IsCancel="True" Padding="18,8" Margin="0,0,10,0"/>
      <Button x:Name="Accept" Content="Deze map gebruiken" IsDefault="True" Padding="18,8"/>
    </StackPanel>
  </StackPanel>
</Window>
"@
    $reader = New-Object Xml.XmlNodeReader $markup
    try { $picker = [Windows.Markup.XamlReader]::Load($reader) } finally { $reader.Close() }
    if ($Owner) { $picker.Owner = $Owner } else { $picker.WindowStartupLocation = 'CenterScreen' }
    $picker.FindName('Description').Text = $Description
    $parts = @{ window=$picker; path=$picker.FindName('FolderPath'); error=$picker.FindName('FolderError'); result=$null }
    $accept = $picker.FindName('Accept'); $accept.Tag = $parts
    $accept.Add_Click({
        param($sender, $eventArgs)
        $controls = $sender.Tag
        try {
            $controls.result = Resolve-A2FolderInput $controls.path.Text
            $controls.window.DialogResult = $true
        } catch {
            $controls.error.Text = $_.Exception.Message; $controls.error.Visibility = 'Visible'
            $null = $controls.path.Focus()
        }
    })
    $browse = $picker.FindName('Browse'); $browse.Tag = $parts
    $browse.Add_Click({
        param($sender, $eventArgs)
        $controls = $sender.Tag
        try {
            $modernType = 'Microsoft.Win32.OpenFolderDialog' -as [type]
            if ($modernType) {
                $browser = [Activator]::CreateInstance($modernType)
                $browser.Title = 'Kies je gamemap of cd-station'
                if ([IO.Directory]::Exists($controls.path.Text)) { $browser.FolderName = $controls.path.Text }
                if ($browser.ShowDialog($controls.window)) { $controls.path.Text = $browser.FolderName }
            } else {
                Add-Type -AssemblyName System.Windows.Forms
                $browser = New-Object Windows.Forms.FolderBrowserDialog
                $browser.Description = 'Kies je gamemap of cd-station'
                $browser.ShowNewFolderButton = $false
                try {
                    if ($browser.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) { $controls.path.Text = $browser.SelectedPath }
                } finally { $browser.Dispose() }
            }
        } catch {
            $controls.error.Text = $_.Exception.Message; $controls.error.Visibility = 'Visible'
        }
    })
    $picker.Add_ContentRendered({ param($sender, $eventArgs); $null = $sender.FindName('FolderPath').Focus() })
    return $parts
}

function Select-A2GameFolder([Windows.Window]$Owner, [string]$Description) {
    $parts = New-A2FolderPickerWindow $Owner $Description
    if ($parts.window.ShowDialog() -eq $true) { return $parts.result }
    return $null
}
