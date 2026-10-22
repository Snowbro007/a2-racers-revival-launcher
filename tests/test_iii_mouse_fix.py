"""Synthetic bytes only: no original game bytes are test fixtures."""
import hashlib
import unittest
from unittest.mock import patch
from tools import iii_mouse_fix as fix


class MouseFixTests(unittest.TestCase):
    def setUp(self):
        source = bytearray(fix.SIZE)
        source[fix.MOUSE_GUID_OFFSET:fix.MOUSE_GUID_OFFSET+16] = fix.MOUSE_GUID
        source[fix.FLAGS_OFFSET-1:fix.FLAGS_OFFSET+8] = bytes.fromhex('6a05528b0850ff5134')
        self.source = bytes(source)
        source[fix.FLAGS_OFFSET] = 6
        self.expected = bytes(source)
        context = fix.CONTEXT[:2]
        self.context = (*context, hashlib.sha256(self.source[context[0]:sum(context)]).hexdigest())
        self.pins = {hashlib.sha256(self.source).hexdigest(): hashlib.sha256(self.expected).hexdigest()}

    def test_changes_only_mouse_cooperative_flag_and_preserves_every_other_byte(self):
        with patch.object(fix, 'CONTEXT', self.context), patch.object(fix, 'PINS', self.pins):
            result, plan = fix.build(self.source)
        self.assertEqual(result, self.expected)
        self.assertEqual([i for i, (a,b) in enumerate(zip(self.source,result)) if a != b], [fix.FLAGS_OFFSET])
        self.assertEqual(self.source[fix.FLAGS_OFFSET], 5)
        self.assertFalse(plan['keyboard_modified'])
        self.assertFalse(plan['runtime_verified'])

    def test_unknown_hash_size_type_and_changed_context_are_rejected(self):
        for value in (self.source, self.source[:-1], bytearray(self.source)):
            with self.assertRaises(ValueError): fix.build(value)
        with patch.object(fix, 'PINS', self.pins), self.assertRaisesRegex(ValueError, 'context'):
            fix.build(self.source)

    def test_output_hash_is_an_independent_final_check(self):
        with patch.object(fix, 'CONTEXT', self.context), patch.object(fix, 'PINS', {hashlib.sha256(self.source).hexdigest():'0'*64}), self.assertRaisesRegex(ValueError,'uitvoer'):
            fix.build(self.source)
