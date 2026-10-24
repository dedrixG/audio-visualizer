"""Unit tests for _dbus_text helper."""

import unittest

import server


class DbusTextTests(unittest.TestCase):
    def test_str_passthrough(self) -> None:
        self.assertEqual(server._dbus_text("hello"), "hello")

    def test_bytes_to_str(self) -> None:
        self.assertEqual(server._dbus_text(b"hello"), "hello")

    def test_none_returns_empty(self) -> None:
        self.assertEqual(server._dbus_text(None), "")

    def test_list_joined_with_comma(self) -> None:
        self.assertEqual(server._dbus_text(["a", "b"]), "a, b")

    def test_int_converts_to_str(self) -> None:
        self.assertEqual(server._dbus_text(42), "42")


if __name__ == "__main__":
    unittest.main()
