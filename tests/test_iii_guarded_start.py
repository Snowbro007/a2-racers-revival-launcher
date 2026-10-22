"""No game executed: Tour 1 must use the shared-mouse copy and process guardian."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import iii_guarded_start as start


class GuardedStartTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1]/'local/test-fixtures'
        base.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root/'local/iii-play/tour1'
        self.target = self.root/'local/iii-mouse/tour1-original'
        self.target.mkdir(parents=True)
        (self.target/'A2 Racer III Tour 1.exe').write_bytes(b'synthetic non-executable parent')

    def test_guarded_original_parent_uses_child_environment_and_never_claims_race_success(self):
        result = {'reason':'exited','cleanup_verified':True,'game_compatibility_verified':False}
        with patch.object(start.iii_mouse_trial,'prepare',return_value=self.target) as prepare, patch.object(start.guard,'supervise_play',return_value=result) as guard, patch.dict(os.environ,{'NOCD':'unchanged'}), redirect_stdout(io.StringIO()):
            self.assertEqual(start.run(self.root,1,'original',self.source),0)
            prepare.assert_called_once_with(self.root,1,'original',self.source)
            argv,cwd,environment=guard.call_args.args
            self.assertEqual(argv,[str(self.target/'A2 Racer III Tour 1.exe')])
            self.assertEqual(cwd,self.target)
            self.assertEqual(environment['NOCD'],self.target.drive[0].upper())
            self.assertEqual(os.environ['NOCD'],'unchanged')
        report=json.loads((self.root/'reports/a2racer3/guarded-runs/tour1-original-last.json').read_text())
        self.assertFalse(report['runtime_verified'])
        self.assertTrue(report['shared_mouse_trial'])

    def test_guard_failure_has_no_unguarded_fallback_or_success_report(self):
        with patch.object(start.iii_mouse_trial,'prepare',return_value=self.target), patch.object(start.guard,'supervise_play',side_effect=OSError('synthetic guard failure')), patch.object(start.guard.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(OSError,'guard failure'):
                start.run(self.root,1,'original',self.source)
            spawn.assert_not_called()
        self.assertFalse((self.root/'reports').exists())

    def test_tour2_and_unknown_target_stop_before_trial_preparation(self):
        with patch.object(start.iii_mouse_trial,'prepare') as prepare:
            for tour,target in ((2,self.source),(1,self.root/'wrong')):
                with self.assertRaises(ValueError): start.run(self.root,tour,'original',target)
            prepare.assert_not_called()
