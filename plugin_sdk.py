"""Plugin SDK for Shadow Media Studio Pro.

Provides base classes and a registry for third-party codec, processor,
and exporter plugins.  Plugins are discovered from:

  1. ``<app-data>/plugins/*.py``  – single-file plugins
  2. ``<app-data>/plugins/<name>/__init__.py``  – package plugins
  3. Any path in the ``SHADOW_PLUGIN_DIRS`` env var (``os.pathsep``-separated)

Each plugin module must define a top-level ``register(registry)`` function
that receives the global :class:`PluginRegistry` and calls its ``add_*``
helpers.

Example single-file plugin (``~/.shadow-media-studio/plugins/my_codec.py``):

.. code-block:: python

    from plugin_sdk import CodecPlugin
    from PIL import Image
    from pathlib import Path

    class MyCodecPlugin(CodecPlugin):
        name = "MyCodec"
        extensions_in = (".myc",)
        extensions_out = (".myc",)

        def decode(self, path: Path) -> Image.Image:
            ...
        def encode(self, image: Image.Image, dest: Path, **kw) -> Path:
            ...

    def register(registry):
        registry.add_codec(MyCodecPlugin())
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from PIL import Image

from settings import get_app_data_dir

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plugin base classes
# ---------------------------------------------------------------------------

class CodecPlugin(ABC):
    """Base class for codec plugins that add input/output format support."""

    name: str = "Unnamed Codec"
    extensions_in: tuple[str, ...] = ()
    extensions_out: tuple[str, ...] = ()
    description: str = ""

    @abstractmethod
    def decode(self, path: Path) -> Image.Image:
        """Open *path* and return a Pillow Image."""
        ...

    @abstractmethod
    def encode(self, image: Image.Image, dest: Path, **kwargs: Any) -> Path:
        """Save *image* to *dest* and return the final path."""
        ...

    def capabilities(self) -> dict[str, bool]:
        """Return a dict of capability flags (alpha, animation, hdr, etc.)."""
        return {}


class ProcessorPlugin(ABC):
    """Base class for image processing step plugins."""

    name: str = "Unnamed Processor"
    description: str = ""

    @abstractmethod
    def process(self, image: Image.Image, **kwargs: Any) -> Image.Image:
        """Transform *image* and return the result (may be in-place)."""
        ...


class ExporterPlugin(ABC):
    """Base class for export destination plugins (e.g. upload to CDN)."""

    name: str = "Unnamed Exporter"
    description: str = ""

    @abstractmethod
    def export(self, source: Path, output: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        """Export the converted file and return status metadata."""
        ...


# ---------------------------------------------------------------------------
# Plugin registry
# ---------------------------------------------------------------------------

@dataclass
class PluginRegistry:
    """Central registry that plugins register themselves with."""

    codecs: list[CodecPlugin] = field(default_factory=list)
    processors: list[ProcessorPlugin] = field(default_factory=list)
    exporters: list[ExporterPlugin] = field(default_factory=list)
    _hooks: dict[str, list[Callable[..., Any]]] = field(default_factory=dict)

    def add_codec(self, plugin: CodecPlugin) -> None:
        self.codecs.append(plugin)
        log.info("Registered codec plugin: %s (%s → %s)",
                 plugin.name, plugin.extensions_in, plugin.extensions_out)

    def add_processor(self, plugin: ProcessorPlugin) -> None:
        self.processors.append(plugin)
        log.info("Registered processor plugin: %s", plugin.name)

    def add_exporter(self, plugin: ExporterPlugin) -> None:
        self.exporters.append(plugin)
        log.info("Registered exporter plugin: %s", plugin.name)

    def add_hook(self, event: str, callback: Callable[..., Any]) -> None:
        """Register a callback for a workflow event.

        Supported events:
          - ``before_convert``  – called with (source_path, settings_dict)
          - ``after_convert``   – called with (source_path, result)
          - ``before_batch``    – called with (file_list, settings_dict)
          - ``after_batch``     – called with (results_list,)
          - ``on_error``        – called with (source_path, exception)
          - ``on_queue_change`` – called with (queue_snapshot,)
        """
        self._hooks.setdefault(event, []).append(callback)
        log.info("Registered hook for event '%s': %s", event, callback.__name__)

    def fire_hook(self, event: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Fire all callbacks registered for *event* and return their results."""
        results: list[Any] = []
        for cb in self._hooks.get(event, []):
            try:
                results.append(cb(*args, **kwargs))
            except Exception as exc:
                log.warning("Hook %s raised %s: %s", cb.__name__, type(exc).__name__, exc)
        return results

    def get_codec(self, name: str) -> CodecPlugin | None:
        for c in self.codecs:
            if c.name.lower() == name.lower():
                return c
        return None

    def get_input_extensions(self) -> set[str]:
        exts: set[str] = set()
        for c in self.codecs:
            exts.update(c.extensions_in)
        return exts

    def get_output_extensions(self) -> set[str]:
        exts: set[str] = set()
        for c in self.codecs:
            exts.update(c.extensions_out)
        return exts


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_registry: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry


# ---------------------------------------------------------------------------
# Plugin discovery and loading
# ---------------------------------------------------------------------------

def _plugin_dirs() -> list[Path]:
    """Collect plugin directories in discovery order."""
    dirs: list[Path] = []
    builtin = get_app_data_dir() / "plugins"
    if builtin.is_dir():
        dirs.append(builtin)
    extra = os.environ.get("SHADOW_PLUGIN_DIRS")
    if extra:
        for p in extra.split(os.pathsep):
            path = Path(p)
            if path.is_dir():
                dirs.append(path)
    return dirs


def discover_plugins(registry: PluginRegistry | None = None) -> PluginRegistry:
    """Scan plugin directories and call each plugin's ``register()`` function."""
    reg = registry or get_registry()
    for plugin_dir in _plugin_dirs():
        for entry in sorted(plugin_dir.iterdir()):
            if entry.name.startswith("_"):
                continue
            module_name: str | None = None
            spec = None
            if entry.is_file() and entry.suffix == ".py":
                module_name = f"shadow_plugin_{entry.stem}"
                spec = importlib.util.spec_from_file_location(module_name, entry)
            elif entry.is_dir() and (entry / "__init__.py").is_file():
                module_name = f"shadow_plugin_{entry.name}"
                spec = importlib.util.spec_from_file_location(module_name, entry / "__init__.py")
            if spec is None or spec.loader is None:
                continue
            try:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = mod  # type: ignore[assignment]
                spec.loader.exec_module(mod)
                register_fn = getattr(mod, "register", None)
                if callable(register_fn):
                    register_fn(reg)
                    log.info("Loaded plugin from %s", entry)
                else:
                    log.warning("Plugin %s has no register() function", entry)
            except Exception as exc:
                log.error("Failed to load plugin %s: %s", entry, exc)
    return reg
