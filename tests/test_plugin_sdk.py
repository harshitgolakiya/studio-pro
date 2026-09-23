"""Tests for the plugin SDK."""
from __future__ import annotations

import tests._headless  # noqa: F401

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


class PluginBaseClassTests(unittest.TestCase):
    """Test plugin SDK base classes and registry."""

    def test_registry_add_codec(self):
        from plugin_sdk import PluginRegistry, CodecPlugin

        class StubCodec(CodecPlugin):
            name = "StubCodec"
            extensions_in = (".stub",)
            extensions_out = (".stub",)
            def decode(self, path): return Image.new("RGB", (1, 1))
            def encode(self, image, dest, **kw):
                dest.write_bytes(b"stub")
                return dest

        reg = PluginRegistry()
        reg.add_codec(StubCodec())
        self.assertEqual(len(reg.codecs), 1)
        self.assertEqual(reg.codecs[0].name, "StubCodec")

    def test_registry_add_processor(self):
        from plugin_sdk import PluginRegistry, ProcessorPlugin

        class StubProcessor(ProcessorPlugin):
            name = "Grayscale+"
            def process(self, image, **kw): return image.convert("L")

        reg = PluginRegistry()
        reg.add_processor(StubProcessor())
        self.assertEqual(len(reg.processors), 1)

    def test_registry_add_exporter(self):
        from plugin_sdk import PluginRegistry, ExporterPlugin

        class StubExporter(ExporterPlugin):
            name = "NullExport"
            def export(self, source, output, metadata): return {"ok": True}

        reg = PluginRegistry()
        reg.add_exporter(StubExporter())
        self.assertEqual(len(reg.exporters), 1)

    def test_hook_fire(self):
        from plugin_sdk import PluginRegistry
        reg = PluginRegistry()
        calls = []
        reg.add_hook("before_convert", lambda *a, **kw: calls.append(1))
        reg.fire_hook("before_convert", "test.png", {})
        self.assertEqual(calls, [1])

    def test_get_codec_by_name(self):
        from plugin_sdk import PluginRegistry, CodecPlugin

        class TestCodec(CodecPlugin):
            name = "TestFmt"
            extensions_in = (".tst",)
            extensions_out = (".tst",)
            def decode(self, path): return Image.new("RGB", (1, 1))
            def encode(self, image, dest, **kw): return dest

        reg = PluginRegistry()
        reg.add_codec(TestCodec())
        found = reg.get_codec("testfmt")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "TestFmt")
        self.assertIsNone(reg.get_codec("nonexistent"))

    def test_get_extensions(self):
        from plugin_sdk import PluginRegistry, CodecPlugin

        class Multi(CodecPlugin):
            name = "Multi"
            extensions_in = (".a", ".b")
            extensions_out = (".c",)
            def decode(self, path): return Image.new("RGB", (1, 1))
            def encode(self, image, dest, **kw): return dest

        reg = PluginRegistry()
        reg.add_codec(Multi())
        self.assertEqual(reg.get_input_extensions(), {".a", ".b"})
        self.assertEqual(reg.get_output_extensions(), {".c"})


class PluginDiscoveryTests(unittest.TestCase):
    """Test plugin auto-discovery from directories."""

    def test_discover_from_dir(self):
        from plugin_sdk import PluginRegistry, discover_plugins

        with tempfile.TemporaryDirectory() as td:
            plugin_dir = Path(td) / "plugins"
            plugin_dir.mkdir()
            # Write a minimal plugin
            (plugin_dir / "test_plugin.py").write_text(
                "from plugin_sdk import ProcessorPlugin\n"
                "class IdentityPlugin(ProcessorPlugin):\n"
                "    name = 'Identity'\n"
                "    def process(self, image, **kw): return image\n"
                "def register(registry):\n"
                "    registry.add_processor(IdentityPlugin())\n"
            )
            reg = PluginRegistry()
            with patch.dict(os.environ, {"SHADOW_PLUGIN_DIRS": str(plugin_dir)}):
                discover_plugins(reg)
            self.assertEqual(len(reg.processors), 1)
            self.assertEqual(reg.processors[0].name, "Identity")

    def test_skip_underscore_files(self):
        from plugin_sdk import PluginRegistry, discover_plugins

        with tempfile.TemporaryDirectory() as td:
            plugin_dir = Path(td) / "plugins"
            plugin_dir.mkdir()
            (plugin_dir / "_private.py").write_text("def register(r): pass\n")
            reg = PluginRegistry()
            with patch.dict(os.environ, {"SHADOW_PLUGIN_DIRS": str(plugin_dir)}):
                discover_plugins(reg)
            # _private should be skipped
            self.assertEqual(len(reg.codecs), 0)
            self.assertEqual(len(reg.processors), 0)
            self.assertEqual(len(reg.exporters), 0)


if __name__ == "__main__":
    unittest.main()
