import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import studio_runtime


class MacModelStorageTests(unittest.TestCase):
    def test_mac_engine_disables_bundle_bytecode_writes_without_changing_parent(self):
        process = Mock(returncode=0)
        process.poll.return_value = 0
        with patch.dict(os.environ, {}, clear=True), patch.object(studio_runtime.sys, "platform", "darwin"), patch.object(studio_runtime.subprocess, "Popen", return_value=process) as launch:
            studio_runtime.run_engine(["office-engine"])
            self.assertEqual(launch.call_args.kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertNotIn("PYTHONDONTWRITEBYTECODE", os.environ)

    def test_signed_bundle_models_seed_writable_user_storage_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundled = root / "app/vendor/models/whisper-base.en"
            bundled.mkdir(parents=True)
            (bundled / "model.bin").write_bytes(b"bundled")
            (bundled / "config.json").write_text("{}")
            user = root / "home/Library/Application Support/Shadow/models/whisper-base.en"
            user.mkdir(parents=True)
            (user / "model.bin").write_bytes(b"user model")
            with patch.dict(os.environ, {}, clear=True), patch.object(studio_runtime.sys, "platform", "darwin"), patch.object(studio_runtime.sys, "frozen", True, create=True), patch.object(studio_runtime, "resource_root", return_value=root / "app"), patch.object(Path, "home", return_value=root / "home"):
                destination = studio_runtime.model_directory()
                self.assertEqual(destination, user.parent)
                self.assertEqual((user / "model.bin").read_bytes(), b"user model")
                self.assertTrue((user / "config.json").is_file())
                self.assertEqual((bundled / "model.bin").read_bytes(), b"bundled")
                # A removed optional/local file is not silently restored every access.
                (user / "config.json").unlink()
                studio_runtime.model_directory()
                self.assertFalse((user / "config.json").exists())

    def test_explicit_model_directory_is_preserved(self):
        with patch.dict(os.environ, {"SHADOW_MODEL_DIR": "custom-models"}), patch.object(studio_runtime.sys, "platform", "darwin"), patch.object(studio_runtime.sys, "frozen", True, create=True):
            self.assertEqual(studio_runtime.model_directory(), Path("custom-models"))

    def test_source_build_keeps_its_vendor_models(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(studio_runtime.sys, "frozen", False, create=True), patch.object(studio_runtime, "resource_root", return_value=Path("source")):
            self.assertEqual(studio_runtime.model_directory(), Path("source/vendor/models"))
