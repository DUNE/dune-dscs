import unittest

from pysnmp.proto.api import v2c
from pysnmp.smi import error

from dune_dscs.emulator.pdu import ROOT, SWITCH, Pdu


class PduTests(unittest.TestCase):
    def test_outlet_readback_and_independent_devices(self):
        first, second = Pdu(2), Pdu(2)
        operation, state = SWITCH + (2, 1, 1), SWITCH + (3, 1, 1)
        first.write_variables((operation, v2c.Integer32(1)))
        self.assertEqual(int(first.read_variables((state, None))[0][1]), 7)
        self.assertEqual(int(second.read_variables((state, None))[0][1]), 8)
        self.assertEqual(int(first.read_variables((ROOT + (3, 2, 2, 1, 4, 1), None))[0][1]), 2)

    def test_invalid_set_changes_no_outlets(self):
        model = Pdu(2)
        first, second = SWITCH + (2, 1, 1), SWITCH + (2, 1, 2)
        for value, expected in ((v2c.Integer32(2), error.WrongValueError),
                                (v2c.OctetString('on'), error.WrongTypeError)):
            with self.subTest(value=value), self.assertRaises(expected):
                model.write_variables((first, v2c.Integer32(1)), (second, value))
            self.assertFalse(any(model.outlets.values()))
        with self.assertRaises(error.NotWritableError):
            model.write_variables((SWITCH + (3, 1, 1), v2c.Integer32(1)))

    def test_walk_and_missing_values(self):
        model = Pdu(2)
        name = (0,)
        walked = []
        while True:
            name, value = model.read_next_variables((name, None))[0]
            if isinstance(value, v2c.EndOfMibView):
                break
            walked.append(tuple(name))
        self.assertEqual(walked, sorted(set(walked)))
        self.assertIn(SWITCH + (3, 1, 2), walked)
        self.assertIsInstance(model.read_variables(((9, 9), None))[0][1], v2c.NoSuchInstance)
