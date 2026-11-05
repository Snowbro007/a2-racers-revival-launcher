"""One resolution naming rule in Python and PowerShell; text only, no launcher or game."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from tools.display_labels import resolution_label
from tools import launcher_model

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ({'width': 1440, 'height': 1080, 'ratio': '4:3', 'status': 'aanbevolen'}, '1440 × 1080 · 4:3 · aanbevolen'),
    ({'width': 640, 'height': 480, 'ratio': '4:3', 'original': True}, 'Origineel · 640 × 480 · 4:3'),
    ({'original': True, 'status': 'unstable'}, 'Origineel · unstable'),
    ({'name': 'Breedbeeld', 'ratio': '16:9'}, 'Breedbeeld · 16:9'),
    ({'width': 1920, 'height': 1080, 'ratio': '16:9'}, '1920 × 1080 · 16:9'),
]
RULE = re.compile(r'^(Origineel( · |$))?([A-Z][a-z]+( · |$))?(\d+ × \d+ · (4:3|16:9)|4:3|16:9)?( · (aanbevolen|untested|unstable|vervallen))?$')


class DisplayLabelTests(unittest.TestCase):
    def test_python_rule(self):
        for arguments, expected in CASES:
            with self.subTest(expected=expected):
                self.assertEqual(resolution_label(**arguments), expected)
        for bad in ({'width': 640}, {'ratio': '21:9'}, {'status': 'aanbevolen!'}, {}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                resolution_label(**bad)

    def test_part_one_resolutions_follow_the_rule(self):
        for key, value in launcher_model.DISPLAY_PROFILES.items():
            with self.subTest(key=key):
                self.assertRegex(value['label'], RULE)
                self.assertNotIn('(', value['label'])

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell')
    def test_powershell_rule_matches_python_and_every_card_has_a_stage(self):
        script = ("$ErrorActionPreference='Stop'\n. '" + str(ROOT / 'tools/launcher_common.ps1') + "'\n"
                  "$out=[ordered]@{}\n"
                  "$out.a=Format-A2Resolution 1440 1080 '4:3' -Status aanbevolen\n"
                  "$out.b=Format-A2Resolution 640 480 '4:3' -Original\n"
                  "$out.c=Format-A2Resolution -Original -Status unstable\n"
                  "$out.d=Format-A2Resolution -Name Breedbeeld -Ratio '16:9'\n"
                  "$out.e=Format-A2Resolution 1920 1080 '16:9'\n"
                  "$out.stages=@('a2racer1','a2racer2','a2racer3','a2racer4','vakantieracer'|ForEach-Object{Get-A2GameStage $_})\n"
                  "$bad=0;foreach($s in @({Format-A2Resolution 640 0 '4:3'},{Format-A2Resolution -Ratio '21:9'},{Format-A2Resolution},{Get-A2GameStage 'x'})){try{& $s;}catch{$bad++}}\n"
                  "$out.bad=$bad\n"
                  "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$out|ConvertTo-Json -Compress")
        host = shutil.which('pwsh') or (Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        result = subprocess.run([str(host), '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        value = json.loads(result.stdout.decode('utf-8-sig'))
        self.assertEqual([value[k] for k in 'abcde'], [expected for _, expected in CASES])
        self.assertEqual(len(value['stages']), 5)
        self.assertTrue(all(value['stages']))
        self.assertEqual(value['bad'], 4)


if __name__ == '__main__':
    unittest.main()
