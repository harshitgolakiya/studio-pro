"""Tests for integrations module."""
from __future__ import annotations

import tests._headless  # noqa: F401

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image


class LocalWebProjectIntegrationTests(unittest.TestCase):
    """Test local web project integration."""

    def test_publish_copies_file_and_creates_manifest(self):
        from integrations import LocalWebProjectIntegration

        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td) / "myproject"
            project_root.mkdir()
            integration = LocalWebProjectIntegration(
                project_root=project_root,
                assets_dir="public/img",
                base_url="/img/",
            )

            # Create a test image
            source = Path(td) / "original.png"
            output = Path(td) / "converted.webp"
            img = Image.new("RGB", (32, 32), (200, 100, 50))
            img.save(str(source))
            img.save(str(output), "WEBP")

            result = integration.publish(source, output, {})
            self.assertEqual(result["status"], "published")

            # Check that file was copied
            dest = project_root / "public" / "img" / "converted.webp"
            self.assertTrue(dest.is_file())

            # Check manifest
            manifest_path = project_root / "public" / "img" / "image-manifest.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text())
            self.assertIn("converted", manifest["images"])
            self.assertEqual(manifest["images"]["converted"]["url"], "/img/converted.webp")

    def test_validate_config_missing_dir(self):
        from integrations import LocalWebProjectIntegration
        integration = LocalWebProjectIntegration(project_root=Path("/nonexistent"))
        errors = integration.validate_config()
        self.assertTrue(len(errors) > 0)


class CloudStorageIntegrationTests(unittest.TestCase):
    """Test cloud storage integration config validation."""

    def test_validate_missing_bucket(self):
        from integrations import CloudStorageIntegration
        integration = CloudStorageIntegration(bucket="")
        errors = integration.validate_config()
        self.assertIn("Bucket name is required", errors)

    def test_validate_unknown_provider(self):
        from integrations import CloudStorageIntegration
        integration = CloudStorageIntegration(bucket="test", provider="dropbox")
        errors = integration.validate_config()
        self.assertTrue(any("Unknown provider" in e for e in errors))


class DesignToolWatchIntegrationTests(unittest.TestCase):
    """Test design tool watch integration."""

    def test_get_watch_patterns(self):
        from integrations import DesignToolWatchIntegration
        integration = DesignToolWatchIntegration(tool="figma")
        patterns = integration.get_watch_patterns()
        self.assertIn("*.png", patterns)
        self.assertIn("*.svg", patterns)

    def test_publish_copies_to_output(self):
        from integrations import DesignToolWatchIntegration

        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "output"
            output_dir.mkdir()
            integration = DesignToolWatchIntegration(
                output_dir=output_dir, tool="generic"
            )
            source = Path(td) / "source.png"
            output = Path(td) / "converted.webp"
            img = Image.new("RGB", (16, 16))
            img.save(str(source))
            img.save(str(output), "WEBP")

            result = integration.publish(source, output, {})
            self.assertEqual(result["status"], "published")
            self.assertTrue((output_dir / "converted.webp").is_file())


class ListIntegrationsTests(unittest.TestCase):
    def test_list_integrations(self):
        from integrations import list_integrations
        integrations = list_integrations()
        self.assertTrue(len(integrations) >= 4)
        names = [cls.__name__ for cls in integrations]
        self.assertIn("LocalWebProjectIntegration", names)
        self.assertIn("CloudStorageIntegration", names)
        self.assertIn("WordPressIntegration", names)


if __name__ == "__main__":
    unittest.main()
