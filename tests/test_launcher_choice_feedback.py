"""Disabled launcher choices stay recognizable and explain their availability."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
XAML = ROOT / "tools/launcher_window.xaml"
NS = {"w": "http://schemas.microsoft.com/winfx/2006/xaml/presentation"}


class ChoiceFeedbackStyleTests(unittest.TestCase):
    def test_disabled_choices_and_buttons_keep_their_explanation_available(self):
        tree = ET.parse(XAML)
        styles = {style.get("TargetType"): style
                  for style in tree.findall("w:Window.Resources/w:Style", NS)
                  if style.get("{http://schemas.microsoft.com/winfx/2006/xaml}Key") is None
                  if style.get("TargetType") in {"Button", "ComboBoxItem"}}
        for target in ("Button", "ComboBoxItem"):
            with self.subTest(target=target):
                setters = styles[target].findall("w:Setter", NS)
                self.assertTrue(any(setter.get("Property") == "ToolTipService.ShowOnDisabled"
                                    and setter.get("Value") == "True" for setter in setters))


FIXTURE = r'''param([string]$Xaml)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase
$reader=New-Object Xml.XmlNodeReader ([xml][IO.File]::ReadAllText($Xaml))
try { $window=[Windows.Markup.XamlReader]::Load($reader) } finally { $reader.Close() }
# No launcher startup or Window.Show. Arrange one ordinary item offscreen so
# real WPF templates, selected/disabled triggers and resource lookup apply.
$item=New-Object Windows.Controls.ComboBoxItem
$item.Style=$window.FindResource([Windows.Controls.ComboBoxItem])
$item.Content='HD HUD test'; $item.ToolTip='De lokale HUD-bestanden ontbreken.'
$item.IsSelected=$true
$surface=New-Object Windows.Controls.Border
$surface.Resources=$window.Resources; $surface.Child=$item
$surface.Measure((New-Object Windows.Size 380,60))
$surface.Arrange((New-Object Windows.Rect 0,0,380,60)); $surface.UpdateLayout()
$null=$item.ApplyTemplate()
$enabled=@{foreground=$item.Foreground.ToString();opacity=$item.Opacity}
$item.IsEnabled=$false; $surface.UpdateLayout()
$disabled=@{foreground=$item.Foreground.ToString();opacity=$item.Opacity;
    enabled=$item.IsEnabled;selected=$item.IsSelected;
    tooltip=[string]$item.ToolTip;show_disabled=[Windows.Controls.ToolTipService]::GetShowOnDisabled($item)}
$item.IsEnabled=$true; $surface.UpdateLayout()
$restored=@{foreground=$item.Foreground.ToString();opacity=$item.Opacity;selected=$item.IsSelected}
# MAX inherits the ordinary Button style; its reason remains available when
# readiness disables it. The test does not invoke its action or show a tooltip.
$max=$window.FindName('MaxProfile')
$max.IsEnabled=$false; $max.ToolTip='De lokale 4K HUD-bestanden ontbreken.'
$maximum=@{enabled=$max.IsEnabled;tooltip=[string]$max.ToolTip;
    show_disabled=[Windows.Controls.ToolTipService]::GetShowOnDisabled($max)}
@{enabled=$enabled;disabled=$disabled;restored=$restored;maximum=$maximum;window_visible=$window.IsVisible} |
    ConvertTo-Json -Depth 4 -Compress
'''


@unittest.skipUnless(os.name == "nt", "Native Windows WPF templates")
class ChoiceFeedbackOffscreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        powershell = shutil.which("pwsh")
        if not powershell:
            raise unittest.SkipTest("PowerShell 7 runtime unavailable")
        parent = ROOT / "local/test-fixtures"
        parent.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix="launcher-choice-feedback-", dir=parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        script = Path(cls.temporary.name) / "feedback.ps1"
        script.write_text(FIXTURE, encoding="utf-8-sig")
        result = subprocess.run(
            [powershell, "-NoProfile", "-STA", "-File", str(script), "-Xaml", str(XAML)],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.result = json.loads(result.stdout.strip())

    def test_disabled_selected_item_is_muted_without_losing_the_selected_choice(self):
        enabled, disabled, restored = (self.result[name]
                                       for name in ("enabled", "disabled", "restored"))
        self.assertFalse(disabled["enabled"])
        self.assertTrue(disabled["selected"])
        self.assertNotEqual(disabled["foreground"], enabled["foreground"])
        self.assertGreater(disabled["opacity"], 0)
        self.assertLess(disabled["opacity"], enabled["opacity"])
        self.assertEqual(restored["foreground"], enabled["foreground"])
        self.assertEqual(restored["opacity"], enabled["opacity"])
        self.assertTrue(restored["selected"])
        self.assertFalse(self.result["window_visible"])

    def test_disabled_hud_item_and_max_keep_their_explanation(self):
        for name in ("disabled", "maximum"):
            with self.subTest(control=name):
                state = self.result[name]
                self.assertFalse(state["enabled"])
                self.assertTrue(state["show_disabled"])
                self.assertIn("ontbreken", state["tooltip"])


if __name__ == "__main__":
    unittest.main()
