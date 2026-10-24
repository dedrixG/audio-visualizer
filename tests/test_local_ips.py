"""Unit tests for local_ips helper."""

import unittest
from unittest import mock

import server


class LocalIpsTests(unittest.TestCase):
    def test_excludes_loopback(self) -> None:
        """local_ips() excludes 127.x addresses."""
        ips = ["127.0.0.1", "192.168.1.5", "10.0.0.2"]
        with mock.patch("subprocess.check_output", return_value=" ".join(ips)):
            result = server.local_ips()
        self.assertNotIn("127.0.0.1", result)
        self.assertIn("192.168.1.5", result)
        self.assertIn("10.0.0.2", result)

    def test_no_duplicates(self) -> None:
        """local_ips() returns a list of strings without duplicates."""
        ips = ["192.168.1.5", "192.168.1.5", "10.0.0.2"]
        with mock.patch("subprocess.check_output", return_value=" ".join(ips)):
            result = server.local_ips()
        self.assertEqual(len(result), len(set(result)))

    def test_returns_strings(self) -> None:
        """local_ips() returns a list of strings."""
        ips = ["192.168.1.5"]
        with mock.patch("subprocess.check_output", return_value=" ".join(ips)):
            result = server.local_ips()
        self.assertIsInstance(result, list)
        for ip in result:
            self.assertIsInstance(ip, str)


if __name__ == "__main__":
    unittest.main()
