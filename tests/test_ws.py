import struct
import unittest

import server


class WsFrameTests(unittest.TestCase):
    def _make_frame(self, opcode: int, payload: bytes, masked: bool = False) -> bytes:
        """Helper to construct a raw WebSocket frame."""
        header = bytearray()
        # FIN bit set, opcode
        header.append(0x80 | opcode)

        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))

        if masked:
            header[1] |= 0x80
            mask = b"\x00\x01\x02\x03"
            header.extend(mask)
            masked_payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            return bytes(header) + masked_payload
        else:
            return bytes(header) + payload

    def test_decode_short_unmasked(self) -> None:
        payload = b"hello"
        frame = self._make_frame(0x1, payload, masked=False)
        result, leftover = server._decode_ws_frame(frame)
        self.assertEqual(result, (0x1, payload))
        self.assertEqual(leftover, b"")

    def test_decode_short_masked(self) -> None:
        payload = b"world"
        frame = self._make_frame(0x2, payload, masked=True)
        result, leftover = server._decode_ws_frame(frame)
        self.assertEqual(result, (0x2, payload))
        self.assertEqual(leftover, b"")

    def test_decode_126_length(self) -> None:
        # Create a payload of exactly 126 bytes
        payload = b"A" * 126
        frame = self._make_frame(0x1, payload, masked=False)
        result, leftover = server._decode_ws_frame(frame)
        self.assertEqual(result, (0x1, payload))
        self.assertEqual(leftover, b"")

    def test_decode_127_length(self) -> None:
        # Create a payload of exactly 65536 bytes
        payload = b"B" * 65536
        frame = self._make_frame(0x2, payload, masked=False)
        result, leftover = server._decode_ws_frame(frame)
        self.assertEqual(result, (0x2, payload))
        self.assertEqual(leftover, b"")

    def test_decode_close_frame(self) -> None:
        payload = b""
        frame = self._make_frame(0x8, payload, masked=False)
        result, leftover = server._decode_ws_frame(frame)
        self.assertEqual(result, (0x8, payload))
        self.assertEqual(leftover, b"")

    def test_decode_incomplete_header(self) -> None:
        # Only send first byte of header
        frame = b"\x81"
        result, leftover = server._decode_ws_frame(frame)
        self.assertIsNone(result)
        self.assertEqual(leftover, frame)

    def test_decode_incomplete_length_126(self) -> None:
        # Send opcode + length byte 126, but no length data
        frame = b"\x81\x7e"
        result, leftover = server._decode_ws_frame(frame)
        self.assertIsNone(result)
        self.assertEqual(leftover, frame)

    def test_decode_incomplete_length_127(self) -> None:
        # Send opcode + length byte 127, but no length data
        frame = b"\x81\x7f"
        result, leftover = server._decode_ws_frame(frame)
        self.assertIsNone(result)
        self.assertEqual(leftover, frame)

    def test_decode_incomplete_mask(self) -> None:
        # Send full header for short frame but only 2 bytes of mask
        payload = b"hi"
        # Construct manually to control exact bytes
        header = bytearray()
        header.append(0x81)  # opcode 1, fin=1
        header.append(0x82)  # masked, len=2
        header.extend(b"\x00\x01")  # partial mask
        frame = bytes(header) + payload
        
        result, leftover = server._decode_ws_frame(frame)
        self.assertIsNone(result)
        self.assertEqual(leftover, frame)

    def test_decode_incomplete_payload(self) -> None:
        # Send full header for short frame but only 1 byte of payload
        payload = b"hi"
        header = bytearray()
        header.append(0x81)
        header.append(0x02)  # len=2
        frame = bytes(header) + payload[:1]
        
        result, leftover = server._decode_ws_frame(frame)
        self.assertIsNone(result)
        self.assertEqual(leftover, frame)


if __name__ == "__main__":
    unittest.main()
