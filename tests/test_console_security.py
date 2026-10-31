import unittest

from ontology_software_factory.console_security import is_loopback_bind, same_origin_request


class ConsoleSecurityTests(unittest.TestCase):
    def test_only_explicit_loopback_hosts_are_allowed(self):
        for host in ("127.0.0.1", "::1", "localhost"):
            with self.subTest(host=host):
                self.assertTrue(is_loopback_bind(host))
        for host in ("0.0.0.0", "::", "192.168.1.10", "example.com", "localhost.localdomain"):
            with self.subTest(host=host):
                self.assertFalse(is_loopback_bind(host))

    def test_same_origin_guard(self):
        self.assertTrue(same_origin_request(None, "127.0.0.1:8766"))
        self.assertTrue(same_origin_request("http://127.0.0.1:8766", "127.0.0.1:8766"))
        self.assertFalse(same_origin_request("https://evil.example", "127.0.0.1:8766"))
        self.assertFalse(same_origin_request("not a url", "127.0.0.1:8766"))


if __name__ == "__main__":
    unittest.main()
