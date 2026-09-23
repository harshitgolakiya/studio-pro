import os
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tests._headless  # noqa: F401
from code_signing import (
    SignatureInfo,
    create_self_signed_certificate,
    find_windows_signtool,
    notarize_macos_dmg,
    sign_macos_bundle,
    sign_windows_binary,
    verify_signature,
)


class TestCodeSigning(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_signature_info_defaults(self):
        info = SignatureInfo(path="test.exe", is_signed=False)
        self.assertEqual(info.path, "test.exe")
        self.assertFalse(info.is_signed)
        self.assertEqual(info.status, "NotSigned")
        d = info.to_dict()
        self.assertEqual(d["path"], "test.exe")
        self.assertFalse(d["is_signed"])

    def test_verify_nonexistent_file(self):
        fake_path = self.tmp / "does_not_exist.exe"
        info = verify_signature(fake_path)
        self.assertFalse(info.is_signed)
        self.assertEqual(info.status, "FileNotFound")

    def test_verify_unsigned_file(self):
        dummy = self.tmp / "dummy.txt"
        dummy.write_text("hello world")
        info = verify_signature(dummy)
        self.assertFalse(info.is_signed)
        self.assertIn(info.status, ("NotSigned", "Unknown", "CheckFailed", "UnsupportedPlatform"))

    def test_find_windows_signtool(self):
        # find_windows_signtool should return str or None without error
        result = find_windows_signtool()
        self.assertTrue(result is None or isinstance(result, str))

    def test_sign_windows_binary_nonexistent(self):
        success, msg = sign_windows_binary(self.tmp / "nonexistent.exe")
        self.assertFalse(success)
        self.assertIn("does not exist", msg)

    def test_sign_windows_binary_no_credentials(self):
        dummy = self.tmp / "dummy.exe"
        dummy.write_text("MZ test")
        with patch("code_signing.find_windows_signtool", return_value=None):
            success, msg = sign_windows_binary(dummy)
            self.assertFalse(success)
            self.assertIn("Neither signtool.exe nor certificate parameters", msg)

    def test_sign_macos_bundle_nonexistent(self):
        success, msg = sign_macos_bundle(self.tmp / "Nonexistent.app", identity="TestID")
        self.assertFalse(success)
        self.assertIn("does not exist", msg)

    def test_notarize_macos_dmg_nonexistent(self):
        success, msg = notarize_macos_dmg(
            self.tmp / "nonexistent.dmg",
            apple_id="user@example.com",
            app_password="app-pass",
            team_id="TEAM123",
        )
        self.assertFalse(success)
        self.assertIn("does not exist", msg)

    def test_create_self_signed_certificate(self):
        pfx_path = self.tmp / "test_cert.pfx"
        result = create_self_signed_certificate(pfx_path, password="secretpassword")
        if result is not None:
            self.assertTrue(result.exists())
            self.assertGreater(result.stat().st_size, 0)

    @patch("subprocess.run")
    def test_sign_windows_binary_signtool_mock(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Successfully signed: dummy.exe"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        dummy = self.tmp / "dummy.exe"
        dummy.write_text("MZ binary")
        cert = self.tmp / "test.pfx"
        cert.write_text("cert")

        success, msg = sign_windows_binary(
            dummy,
            cert_path=cert,
            cert_password="password",
            signtool_path="C:\\mock\\signtool.exe",
        )
        self.assertTrue(success)
        self.assertIn("Signed successfully", msg)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("/fd", cmd)
        self.assertIn("SHA256", cmd)

    @patch("subprocess.run")
    def test_sign_macos_bundle_mock(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Signed: Test.app"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        app_dir = self.tmp / "Test.app"
        app_dir.mkdir()

        success, msg = sign_macos_bundle(app_dir, identity="Developer ID Application: Test")
        self.assertTrue(success)
        self.assertIn("Signed macOS bundle", msg)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("codesign", cmd)
        self.assertIn("--options", cmd)
        self.assertIn("runtime", cmd)


if __name__ == "__main__":
    unittest.main()
