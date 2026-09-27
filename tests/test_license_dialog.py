from __future__ import annotations

import unittest

from license_dialog import valid_purchase_url


class LicenseDialogConfigurationTests(unittest.TestCase):
    def test_purchase_url_requires_real_https_destination(self) -> None:
        self.assertTrue(valid_purchase_url("https://store.example.com/shadow"))
        self.assertFalse(valid_purchase_url(""))
        self.assertFalse(valid_purchase_url("javascript:alert(1)"))
        self.assertFalse(valid_purchase_url("http://store.example.com/shadow"))


if __name__ == "__main__":
    unittest.main()
