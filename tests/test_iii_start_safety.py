"""Tour 2 stops before writes; Tour 1 can only enter the mandatory guard."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import iii_local_launcher as local, iii_compat_launcher as compat
from tools import iii_start_safety as safety
from tools import launcher_model as model


class IIIStartSafetyTests(unittest.TestCase):
    def test_every_start_route_stops_before_prepare_process_and_file_writes(self):
        parent=Path(__file__).resolve().parents[1]/'local/test-fixtures'
        parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='iii-start-block-',dir=parent) as directory:
            root=Path(directory)
            for tour in (2,):
                routes=[(local,(root,tour))]+[(compat,(root,tour,profile)) for profile in compat.PROFILES]
                for runner,args in routes:
                    with self.subTest(tour=tour,runner=runner.__name__,args=args),patch.object(runner,'prepare') as prepare,patch.object(runner.subprocess,'Popen') as spawn:
                        with self.assertRaisesRegex(ValueError,'muis vast'):
                            runner.start(*args)
                        prepare.assert_not_called();spawn.assert_not_called()
                        self.assertEqual(list(root.iterdir()),[])

    def test_cli_starts_also_stop_before_preparation_and_leave_environment_intact(self):
        before=dict(os.environ)
        for runner,args in ((local,['start','--tour','2']),
                            (compat,['start','--tour','2','--profile','fullhd-skyoff'])):
            with self.subTest(runner=runner.__name__),patch('sys.argv',['synthetic.py',*args]),patch.object(runner,'prepare') as prepare,patch.object(runner.subprocess,'Popen') as spawn,contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(runner.main(),1)
                self.assertIn(safety.BLOCK_REASON,errors.getvalue())
                prepare.assert_not_called();spawn.assert_not_called()
        self.assertEqual(dict(os.environ),before)

    def test_catalog_has_no_available_iii_start_profile_even_with_verified_files(self):
        parent=Path(__file__).resolve().parents[1]/'local/test-fixtures'
        parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='iii-status-block-',dir=parent) as directory:
            root=Path(directory)
            for tour in (1,2):
                folder=root/f'local/iii-prepared/baseline-20261013/tour{tour}'
                folder.mkdir(parents=True)
                for name in ('spel.dat','raser.ini',f'A2 Racer III Tour {tour}.exe'):
                    (folder/name).write_bytes(b'synthetic non-executable data')
            with patch.object(model.hashlib,'file_digest') as pin,patch.object(local,'check',return_value={'launch_ready':True}),patch.object(compat,'available',return_value={'available':True,'reason':'synthetic'}):
                # The known Tour 1 source pin makes one tour look fully ready.
                pin.return_value.hexdigest.return_value='4754e7d6374563103ff56ead0eeb685f8e90bcd8e211c9cd30bf37f92eb00f8d'
                status=model.iii_preparation(root)
            self.assertTrue(status['tours']['1']['launch_ready'])
            first,second=status['tours']['1'],status['tours']['2']
            self.assertFalse(first['start_blocked'])
            self.assertTrue(first['guard_required'])
            self.assertTrue(all(profile['available'] for profile in first['profiles'].values()))
            self.assertTrue(second['start_blocked'])
            for profile in second['profiles'].values():
                self.assertFalse(profile['available'])
                self.assertEqual(profile['reason'],safety.BLOCK_REASON)

    def test_no_user_environment_override_can_enable_the_stop(self):
        with patch.dict(os.environ,{'A2_REVIVAL_III_START':'1','A2_REVIVAL_III_SAFE':'true'}):
            self.assertFalse(safety.status(2,'compat')['start_allowed'])
            self.assertTrue(safety.status(2,'compat')['start_blocked'])
            with self.assertRaises(ValueError):safety.assert_start_allowed(2,'compat')
            self.assertTrue(safety.status(1,'compat')['guard_required'])
            for tour,profile in ((True,'compat'),(1,'unknown'),(None,None)):
                with self.assertRaises(ValueError):safety.assert_start_allowed(tour,profile)
