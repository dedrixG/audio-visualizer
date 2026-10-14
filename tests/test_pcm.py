import array
import unittest

import server


class PcmTests(unittest.TestCase):
    def test_stereo_to_mono(self) -> None:
        raw = array.array("f", [1.0, 3.0, 0.0, 2.0]).tobytes()
        mono = array.array("f")
        mono.frombytes(server._stereo_to_mono(raw))
        self.assertEqual(list(mono), [2.0, 1.0])

    def test_downmix_keeps_front_pair(self) -> None:
        raw = array.array("f", [1.0, 2.0, 9.0, 3.0, 4.0, 8.0]).tobytes()
        stereo = array.array("f")
        stereo.frombytes(server._to_stereo_f32(raw, 3))
        self.assertEqual(list(stereo), [1.0, 2.0, 3.0, 4.0])

    def test_mono_duplicates(self) -> None:
        raw = array.array("f", [0.5, -0.5]).tobytes()
        stereo = array.array("f")
        stereo.frombytes(server._to_stereo_f32(raw, 1))
        self.assertEqual(list(stereo), [0.5, 0.5, -0.5, -0.5])

    def test_port_in_use(self) -> None:
        self.assertTrue(server.port_in_use(OSError(98, "in use")))
        self.assertTrue(server.port_in_use(OSError(10048, "in use")))
        self.assertFalse(server.port_in_use(OSError(13, "denied")))

    def test_now_playing_script_ships(self) -> None:
        path = server.now_playing_script()
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
