"""Synthetic byte-plan and rendering contracts; no game inputs or native execution."""
import copy
import struct
import unittest
from unittest.mock import patch
from tools import later_native as b


def synthetic(game,kind):
    spec=copy.deepcopy(b.SPECS[game]);size,_=spec[kind];raw=bytearray(size)
    if kind=='menu':
        offset,before=spec['display'];raw[offset:offset+6]=bytes.fromhex(before)
        if game=='a2racer4':raw[0xa51f0:0xa51f5]=bytes.fromhex('e8dbf2ffff')
    else:
        o,before,after=spec['setter'];raw[o:o+len(bytes.fromhex(before))]=bytes.fromhex(before)
        raw[spec['table']:spec['table']+8]=struct.pack('<2I',640,480)
        start=spec['keyboard']
        for offset,data in [(0,'8b088dbedc000000'),(0x12,'3d1e0007800f8588000000'),
                            (0x2c,'0f85cf000000'),(0x45,'85c00f84b4000000')]:
            data=bytes.fromhex(data);raw[start+offset:start+offset+len(data)]=data
    raw=bytes(raw);spec[kind]=(len(raw),b.sha(raw))
    return raw,spec


def keyboard_vm(raw,pc,*,eax=0,edi=0x1000,stop=()):
    """Small independent interpreter for the emitted detour instructions only."""
    regs={'eax':eax,'edi':edi,'esi':0x1000-0xdc,'ecx':0};stack=[];equal=False
    keys=bytearray(b'\xff'*256)
    for _ in range(100):
        if pc in stop:return pc,regs,keys
        op=raw[pc]
        if op==0xe9:pc+=5+struct.unpack_from('<i',raw,pc+1)[0]
        elif op==0xeb:pc+=2+struct.unpack_from('<b',raw,pc+1)[0]
        elif op==0x3d:equal=regs['eax']==struct.unpack_from('<I',raw,pc+1)[0];pc+=5
        elif raw[pc:pc+2]==b'\x0f\x84':pc+=6+(struct.unpack_from('<i',raw,pc+2)[0] if equal else 0)
        elif op==0x74:pc+=2+(struct.unpack_from('<b',raw,pc+1)[0] if equal else 0)
        elif op==0x50:stack.append(regs['eax']);pc+=1
        elif op==0x58:regs['eax']=stack.pop();pc+=1
        elif raw[pc:pc+2]==b'\x33\xc0':regs['eax']=0;pc+=2
        elif op==0xb9:regs['ecx']=struct.unpack_from('<I',raw,pc+1)[0];pc+=5
        elif raw[pc:pc+2]==b'\xf3\xab':
            assert regs['edi']==0x1000 and regs['ecx']==64
            keys[:]=struct.pack('<I',regs['eax'])*64;regs['edi']+=256;regs['ecx']=0;pc+=2
        elif raw[pc:pc+2]==b'\x8d\xbe':regs['edi']=regs['esi']+struct.unpack_from('<I',raw,pc+2)[0];pc+=6
        elif raw[pc:pc+2]==b'\x8b\x08':regs['ecx']=123;pc+=2
        else:raise AssertionError('Unexpected detour opcode '+hex(op)+' at '+hex(pc))
    raise AssertionError('Detour did not terminate')


class BinaryTests(unittest.TestCase):
    def setUp(self):
        # The mouse builder has its own exact-version and machine-code tests.
        # Keep these synthetic wrapper/keyboard fixtures independent of it.
        effect=patch('tools.later_mouse_input.patch',side_effect=lambda raw:(raw,{'patches':[]}))
        self.mouse_patch=effect.start();self.addCleanup(effect.stop)
        effect=patch('tools.later_joystick_input.patch',side_effect=lambda raw:(raw,{'patches':[]}))
        self.joystick_patch=effect.start();self.addCleanup(effect.stop)
        effect=patch('tools.later_iv_mouse_input.patch',side_effect=lambda raw:(raw,{'patches':[]}))
        self.iv_mouse_patch=effect.start();self.addCleanup(effect.stop)
        effect=patch('tools.later_iv_joystick_input.patch',side_effect=lambda raw:(raw,{'patches':[]}))
        self.iv_joystick_patch=effect.start();self.addCleanup(effect.stop)
        effect=patch('tools.later_iv_texture_formats.patch',side_effect=lambda raw:(raw,{'patches':[]}))
        self.iv_texture_patch=effect.start();self.addCleanup(effect.stop)
        effect=patch('tools.later_vacation_texture_formats.patch',side_effect=lambda raw:(raw,{'patches':[]}))
        self.vr_texture_patch=effect.start();self.addCleanup(effect.stop)
        effect=patch('tools.later_iv_vram_probe.patch',side_effect=lambda raw:(raw,{'patches':[]}))
        self.iv_probe_patch=effect.start();self.addCleanup(effect.stop)
        effect=patch('tools.later_mouse_shutdown.patch',side_effect=lambda raw,game:(raw,{'patches':[]}))
        self.shutdown_patch=effect.start();self.addCleanup(effect.stop)

    def test_iv_vram_bound_composes_only_with_iv_race_and_rejects_overlap(self):
        raw,spec=synthetic('a2racer4','race');entry={'offset':0x360,'before':'00','after':'90'}
        self.iv_probe_patch.side_effect=lambda data:(data,{'patches':[entry]})
        with patch.dict(b.SPECS,{'a2racer4':spec}):
            output,_=b.patch_binary(raw,'a2racer4','race')
        self.assertEqual(output[0x360],0x90);self.iv_probe_patch.assert_called_once_with(raw)
        self.iv_probe_patch.reset_mock()
        other,other_spec=synthetic('vakantieracer','race')
        with patch.dict(b.SPECS,{'vakantieracer':other_spec}):b.patch_binary(other,'vakantieracer','race')
        self.iv_probe_patch.assert_not_called()
        self.iv_texture_patch.side_effect=lambda data:(data,{'patches':[entry]})
        with patch.dict(b.SPECS,{'a2racer4':spec}),self.assertRaisesRegex(ValueError,'overlap'):
            b.patch_binary(raw,'a2racer4','race')

    def test_shutdown_fix_composes_for_each_race_only_and_rejects_overlapping_patches(self):
        for game,mouse in (('a2racer4',self.iv_mouse_patch),('vakantieracer',self.mouse_patch)):
            self.shutdown_patch.reset_mock()
            raw,spec=synthetic(game,'race')
            entry={'offset':0x380,'before':'00','after':'90'}
            self.shutdown_patch.side_effect=lambda data,selected:(data,{'patches':[entry]})
            with patch.dict(b.SPECS,{game:spec}):
                output,plan=b.patch_binary(raw,game,'race')
            self.assertEqual(output[0x380],0x90)
            self.shutdown_patch.assert_called_once_with(raw,game)
            self.assertFalse(plan['runtime_verified'])
            mouse.side_effect=lambda data:(data,{'patches':[entry]})
            with patch.dict(b.SPECS,{game:spec}),self.assertRaisesRegex(ValueError,'overlap'):
                b.patch_binary(raw,game,'race')
            mouse.side_effect=lambda data:(data,{'patches':[]})
            self.shutdown_patch.reset_mock()
            menu,menu_spec=synthetic(game,'menu')
            with patch.dict(b.SPECS,{game:menu_spec}): b.patch_binary(menu,game,'menu')
            self.shutdown_patch.assert_not_called()

    def test_texture_filter_composition_is_version_scoped_and_rejects_overlap(self):
        for game,own,other,input_mock in (
                ('a2racer4',self.iv_texture_patch,self.vr_texture_patch,self.iv_mouse_patch),
                ('vakantieracer',self.vr_texture_patch,self.iv_texture_patch,self.mouse_patch)):
            self.iv_texture_patch.reset_mock();self.vr_texture_patch.reset_mock()
            raw,spec=synthetic(game,'race');entry={'offset':0x350,'before':'00','after':'90'}
            own.side_effect=lambda data:(data,{'patches':[entry]})
            with patch.dict(b.SPECS,{game:spec}):
                output,_=b.patch_binary(raw,game,'race')
            self.assertEqual(output[0x350],0x90);own.assert_called_once_with(raw)
            other.assert_not_called()
            input_mock.side_effect=lambda data:(data,{'patches':[entry]})
            with patch.dict(b.SPECS,{game:spec}),self.assertRaisesRegex(ValueError,'overlap'):
                b.patch_binary(raw,game,'race')
            input_mock.side_effect=lambda data:(data,{'patches':[]})

    def test_iv_joystick_is_composed_only_for_iv_race_and_cannot_overlap_mouse(self):
        raw,spec=synthetic('a2racer4','race');offset=0x300
        entry={'offset':offset,'before':'00','after':'90'}
        self.iv_joystick_patch.side_effect=lambda data:(data,{'patches':[entry]})
        with patch.dict(b.SPECS,{'a2racer4':spec}):
            output,_=b.patch_binary(raw,'a2racer4','race')
        self.assertEqual(output[offset],0x90)
        self.iv_joystick_patch.assert_called_once_with(raw)
        self.iv_joystick_patch.reset_mock()
        vr,vr_spec=synthetic('vakantieracer','race')
        with patch.dict(b.SPECS,{'vakantieracer':vr_spec}):b.patch_binary(vr,'vakantieracer','race')
        self.iv_joystick_patch.assert_not_called()
        self.iv_mouse_patch.side_effect=lambda data:(data,{'patches':[entry]})
        with patch.dict(b.SPECS,{'a2racer4':spec}),self.assertRaisesRegex(ValueError,'overlap'):
            b.patch_binary(raw,'a2racer4','race')

    def test_mouse_changes_are_composed_only_for_vacation_race(self):
        raw,spec=synthetic('vakantieracer','race');offset=0x200
        self.mouse_patch.side_effect=lambda data:(data[:offset]+b'\x90'+data[offset+1:],
            {'patches':[{'offset':offset,'before':'00','after':'90'}]})
        with patch.dict(b.SPECS,{'vakantieracer':spec}):
            output,_=b.patch_binary(raw,'vakantieracer','race')
        self.assertEqual(output[offset],0x90);self.mouse_patch.assert_called_once_with(raw)
        self.joystick_patch.assert_called_once_with(raw)
        self.mouse_patch.reset_mock()
        self.joystick_patch.reset_mock()
        raw,spec=synthetic('a2racer4','race')
        with patch.dict(b.SPECS,{'a2racer4':spec}):b.patch_binary(raw,'a2racer4','race')
        self.mouse_patch.assert_not_called()
        self.joystick_patch.assert_not_called()
        self.iv_mouse_patch.assert_called_once_with(raw)

    def test_joystick_changes_are_composed_with_other_vacation_fixes(self):
        raw,spec=synthetic('vakantieracer','race');offset=0x300
        self.joystick_patch.side_effect=lambda data:(data[:offset]+b'\x90'+data[offset+1:],
            {'patches':[{'offset':offset,'before':'00','after':'90'}]})
        with patch.dict(b.SPECS,{'vakantieracer':spec}):
            output,_=b.patch_binary(raw,'vakantieracer','race')
        self.assertEqual(output[offset],0x90);self.joystick_patch.assert_called_once_with(raw)

    def test_joystick_changes_cannot_overlap_the_mouse_patch(self):
        raw,spec=synthetic('vakantieracer','race');offset=0x200
        entry={'offset':offset,'before':'00','after':'90'}
        self.mouse_patch.side_effect=lambda data:(data,{'patches':[entry]})
        self.joystick_patch.side_effect=lambda data:(data,{'patches':[entry]})
        with patch.dict(b.SPECS,{'vakantieracer':spec}),self.assertRaisesRegex(ValueError,'overlap'):
            b.patch_binary(raw,'vakantieracer','race')

    def test_mouse_changes_cannot_overlap_the_keyboard_patch(self):
        raw,spec=synthetic('vakantieracer','race');offset=spec['keyboard']
        self.mouse_patch.side_effect=lambda data:(data,
            {'patches':[{'offset':offset,'before':data[offset:offset+8].hex(),'after':'90'*8}]})
        with patch.dict(b.SPECS,{'vakantieracer':spec}),self.assertRaisesRegex(ValueError,'overlap'):
            b.patch_binary(raw,'vakantieracer','race')

    def test_both_versions_patch_only_declared_regions_and_refuse_reapplication(self):
        for game in b.SPECS:
            for kind in ('menu','race'):
                raw,spec=synthetic(game,kind)
                with self.subTest(game=game,kind=kind),patch.dict(b.SPECS,{game:spec}):
                    output,plan=b.patch_binary(raw,game,kind)
                    allowed={i for p in plan['patches'] for i in range(p['offset'],p['offset']+len(bytes.fromhex(p['before'])))}
                    self.assertTrue({i for i,(a,c) in enumerate(zip(raw,output)) if a!=c}<=allowed)
                    self.assertEqual(len(output),len(raw));self.assertFalse(plan['runtime_verified'])
                    with self.assertRaises(ValueError):b.patch_binary(output,game,kind)

    def test_compatibility_candidate_preserves_native_640_screen_record(self):
        for game in b.SPECS:
            raw,spec=synthetic(game,'race')
            with patch.dict(b.SPECS,{game:spec}):
                output,plan=b.patch_binary(raw,game,'race')
            offset=spec['table']
            self.assertEqual(output[offset:offset+8],struct.pack('<2I',640,480))
            self.assertFalse(any(p['offset']==offset for p in plan['patches']))

    def test_unknown_hash_role_and_game_are_rejected(self):
        for game,kind in [('a2racer4','race'),('vakantieracer','menu'),('other','menu'),('a2racer4','other')]:
            with self.assertRaises(ValueError):b.patch_binary(b'synthetic',game,kind)

    def test_keyboard_hresult_routing_keeps_unknown_errors_fatal(self):
        for game in b.SPECS:
            raw,spec=synthetic(game,'race');start=spec['keyboard']
            with patch.dict(b.SPECS,{game:spec}):output,_=b.patch_binary(raw,game,'race')
            acquire,general=start+0x1d,start+0xa5
            for hr in (0,0x8007001e,0x8007000c,0x80004005,0x8007000e):
                stop,regs,keys=keyboard_vm(output,start+0x12,eax=hr,stop=(acquire,general))
                self.assertEqual(stop,acquire if hr in (0x8007001e,0x8007000c) else general)
                self.assertEqual(regs['eax'],hr)

    def test_failed_retry_clears_keys_only_for_two_known_transient_errors(self):
        for game in b.SPECS:
            raw,spec=synthetic(game,'race');start=spec['keyboard']
            with patch.dict(b.SPECS,{game:spec}):output,_=b.patch_binary(raw,game,'race')
            for hr in (0,0x8007001e,0x8007000c,0x80004005,0x8007000e):
                stop,regs,keys=keyboard_vm(output,start+0x45,eax=hr,stop=(start+0xa5,start+0x101))
                transient=hr in (0x8007001e,0x8007000c)
                self.assertEqual(stop,start+0x101 if transient else start+0xa5)
                self.assertEqual(keys,bytearray(256) if transient else bytearray(b'\xff'*256))

    def test_poll_initialization_clears_previous_keys_and_preserves_device_pointer(self):
        raw,spec=synthetic('a2racer4','race');start=spec['keyboard']
        with patch.dict(b.SPECS,{'a2racer4':spec}):output,_=b.patch_binary(raw,'a2racer4','race')
        stop,regs,keys=keyboard_vm(output,start,eax=0x123456,stop=(start+8,))
        self.assertEqual(regs['eax'],0x123456);self.assertEqual(regs['edi'],0x1000)
        self.assertEqual(keys,bytearray(256))

    def test_ini_edits_are_section_bound_preserve_other_bytes_and_refuse_duplicates(self):
        raw=b'[OTHER]\r\nkey=keep\r\n[PROGRAM]\r\nkey = old  ; note\r\n'
        self.assertEqual(b.set_ini(raw,'PROGRAM','key','new'),raw.replace(b'old',b'new'))
        for invalid in (b'[PROGRAM]\n',b'[PROGRAM]\nkey=1\nkey=2\n'):
            with self.assertRaises(ValueError):b.set_ini(invalid,'PROGRAM','key','new')

    def test_both_native_16bit_requests_keep_other_sections_and_disable_verbose_logging(self):
        raw=b'[HELPDESK]\r\nDEBUGON=1\r\n[PROGRAM]\r\nRESOLUTION=3\r\nWINDOWED=1\r\nOTHER=keep\r\n[OTHER]\r\nDEBUGON=1\r\nWINDOWED=1\r\n'
        for game in b.SPECS:
            expected=raw.replace(b'DEBUGON=1',b'DEBUGON=0',1)
            self.assertEqual(b.race_ini(raw,game),expected)
            self.assertEqual(b.race_ini(expected,game),expected)
        with self.assertRaises(ValueError):b.race_ini(raw,'unknown')

    def test_wrapper_keeps_windowed_virtual_16bit_and_unforced_native_rendering(self):
        raw=b'[General]\nCaptureMouse=true\nCenterAppWindow=false\nFullScreenMode=true\nScalingMode=unspecified\n[GeneralExt]\nWindowedAttributes=\nDesktopBitDepth=32\n[DirectX]\nVRAM=256\nResolution=h:1920, v:1080\nAppControlledScreenMode=true\nForceVerticalSync=false\ndgVoodooWatermark=true\n'
        with patch.dict(b.trial_manifest.DGVOODOO_CONFIG_SOURCE,{'sha256':b.sha(raw)}):
            out=b.race_config(raw)
        self.assertIn(b'Resolution=unforced',out)
        self.assertIn(b'DesktopBitDepth=16',out)
        self.assertIn(b'VRAM=32',out)
        self.assertIn(b'CaptureMouse=false',out)
        self.assertIn(b'WindowedAttributes=borderless',out)
        self.assertIn(b'FullScreenMode=false',out)
        self.assertIn(b'AppControlledScreenMode=false',out)
        with self.assertRaises(ValueError):b.race_config(b'unknown')



class PublicProfileTests(unittest.TestCase):
    CONFIG = (b'[General]\r\nCaptureMouse=true\r\nCenterAppWindow=false\r\nFullScreenMode=true\r\n'
              b'ScalingMode=unspecified\r\n[GeneralExt]\r\nWindowedAttributes=\r\nDesktopBitDepth=32\r\n'
              b'[Glide]\r\nResolution=do-not-change\r\n[DirectX]\r\nVRAM=256\r\nResolution=unforced\r\n'
              b'AppControlledScreenMode=true\r\nForceVerticalSync=false\r\ndgVoodooWatermark=true\r\n')

    def test_hd_changes_resolution_and_presentation_but_keeps_original_aspect(self):
        with patch.dict(b.trial_manifest.DGVOODOO_CONFIG_SOURCE, {'sha256': b.sha(self.CONFIG)}):
            compat = b.race_config(self.CONFIG, 'compat')
            hd = b.race_config(self.CONFIG, 'hd1080')
        expected = compat.replace(b'Resolution=unforced', b'Resolution=h:1440, v:1080')
        expected = expected.replace(b'WindowedAttributes=borderless\r\n', b'WindowedAttributes=borderless,fullscreensize\r\n')
        self.assertEqual(hd, expected)
        self.assertIn(b'[Glide]\r\nResolution=do-not-change', hd)
        self.assertIn(b'ScalingMode=stretched_ar', hd)
        self.assertIn(b'DesktopBitDepth=16', hd)
        self.assertIn(b'VRAM=32', hd)
        self.assertIn(b'FullScreenMode=false', hd)
        self.assertIn(b'AppControlledScreenMode=false', hd)
        for profile, render in [('compat', [640, 480]), ('hd1080', [1440, 1080])]:
            info = b.profile_metadata(profile)
            self.assertEqual(info['logical_canvas_requested'], [640, 480])
            self.assertEqual(info['render_resolution_requested'], render)
            self.assertEqual(info['race_aspect_ratio_requested'], [4, 3])
            self.assertFalse(info['widescreen_requested'])

    def test_menu_and_race_request_separate_renderers_and_quiet_loading(self):
        self.assertIn(b'renderer=gdi', b.MENU_CONFIG)
        self.assertIn(b'maxfps=60', b.MENU_CONFIG)
        self.assertIn(b'aspect_ratio=4:3', b.MENU_CONFIG)
        ini = b'[PROGRAM]\r\nRESOLUTION=1\r\nWINDOWED=9\r\n[HELPDESK]\r\nDEBUGON=1\r\n'
        for game in b.SPECS:
            for profile, windowed in [('compat', b'1'), ('hd1080', b'0')]:
                value = b.race_ini(ini, game, profile)
                self.assertIn(b'RESOLUTION=3', value)
                self.assertIn(b'WINDOWED=' + windowed, value)
                self.assertIn(b'DEBUGON=0', value)

    def test_ini_accepts_cp1252_paths_without_changing_comments_or_other_sections(self):
        raw = b'[OTHER]\r\nINTROAVI=keep\r\n[GENERAL]\r\n  INTROAVI = old  ; note\r\n'
        value = r'Y:\Spellen\Mënü\INTRO1.MPG'
        expected = raw.replace(b'old', value.encode('cp1252'))
        self.assertEqual(b.set_ini(raw, 'GENERAL', 'INTROAVI', value), expected)
        with self.assertRaises(UnicodeEncodeError):
            b.set_ini(raw, 'GENERAL', 'INTROAVI', '\U0001f680')
        with self.assertRaises(ValueError):
            b.set_ini(raw + b'INTROAVI=duplicate\r\n', 'GENERAL', 'INTROAVI', value)

    def test_input_kind_and_profile_are_fail_closed(self):
        for game, kind in [('unknown', 'race'), ('a2racer4', 'unknown')]:
            with self.assertRaises(ValueError):
                b.patch_binary(b'', game, kind)
        for game, profile in [('unknown', 'compat'), ('a2racer4', 'widescreen')]:
            with self.assertRaises(ValueError):
                b.validate_profile(game, profile)
        with self.assertRaises(ValueError):
            b.profile_metadata('4k')
        with self.assertRaises(ValueError):
            b.race_config(b'unrecognized configuration', 'hd1080')


if __name__ == "__main__":
    unittest.main()
