"""Tests for workflow hooks."""
from __future__ import annotations

import tests._headless  # noqa: F401

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class HookManagerTests(unittest.TestCase):
    """Test the HookManager callback system."""

    def test_register_and_fire(self):
        from workflow_hooks import HookManager
        hm = HookManager()
        results = []
        hm.register("before_convert", lambda ctx: results.append(ctx["event"]))
        hm.fire("before_convert", {"source": "test.png"})
        self.assertEqual(results, ["before_convert"])

    def test_invalid_event_raises(self):
        from workflow_hooks import HookManager
        hm = HookManager()
        with self.assertRaises(ValueError):
            hm.register("invalid_event", lambda ctx: None)

    def test_unregister(self):
        from workflow_hooks import HookManager
        hm = HookManager()
        cb = lambda ctx: None  # noqa: E731
        hm.register("after_convert", cb)
        hm.unregister("after_convert", cb)
        self.assertEqual(len(hm._callbacks.get("after_convert", [])), 0)

    def test_disabled_hooks_no_fire(self):
        from workflow_hooks import HookManager
        hm = HookManager(enabled=False)
        results = []
        hm.register("before_convert", lambda ctx: results.append(1))
        hm.fire("before_convert")
        self.assertEqual(results, [])

    def test_fire_before_convert_helper(self):
        from workflow_hooks import HookManager
        hm = HookManager()
        contexts = []
        hm.register("before_convert", lambda ctx: contexts.append(ctx))
        hm.fire_before_convert(Path("test.png"), {"quality": 80})
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["source"], "test.png")
        self.assertEqual(contexts[0]["settings"]["quality"], 80)

    def test_fire_after_convert_helper(self):
        from workflow_hooks import HookManager
        hm = HookManager()
        contexts = []
        hm.register("after_convert", lambda ctx: contexts.append(ctx))
        hm.fire_after_convert(Path("a.png"), Path("a.webp"), "Completed",
                              {"original_size": 1000, "output_size": 500})
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["status"], "Completed")

    def test_fire_on_error_helper(self):
        from workflow_hooks import HookManager
        hm = HookManager()
        contexts = []
        hm.register("on_error", lambda ctx: contexts.append(ctx))
        hm.fire_on_error(Path("bad.png"), ValueError("bad image"))
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["error_type"], "ValueError")

    def test_fire_batch_helpers(self):
        from workflow_hooks import HookManager
        hm = HookManager()
        contexts = []
        hm.register("before_batch", lambda ctx: contexts.append(ctx))
        hm.register("after_batch", lambda ctx: contexts.append(ctx))
        hm.fire_before_batch(["a.png", "b.png"], {"format": "WEBP"})
        hm.fire_after_batch([{"status": "Completed"}, {"status": "Failed"}])
        self.assertEqual(len(contexts), 2)
        self.assertEqual(contexts[0]["total"], 2)
        self.assertEqual(contexts[1]["completed"], 1)
        self.assertEqual(contexts[1]["failed"], 1)

    def test_script_hook_execution(self):
        """Test that Python script hooks are executed."""
        import sys
        from workflow_hooks import HookManager, _find_script_hooks, _run_script_hook
        with tempfile.TemporaryDirectory() as td:
            hooks_dir = Path(td) / "hooks"
            hooks_dir.mkdir()
            script = hooks_dir / "before_convert.py"
            script.write_text(
                "import sys, json\n"
                "ctx = json.load(sys.stdin)\n"
                "print(json.dumps({'received': True, 'event': ctx.get('event')}))\n"
            )
            with patch("workflow_hooks._hooks_dir", return_value=hooks_dir):
                scripts = _find_script_hooks("before_convert")
                self.assertEqual(len(scripts), 1)
                result = _run_script_hook(scripts[0], {"event": "before_convert", "source": "test.png"})
                self.assertEqual(result["returncode"], 0)


class HookManagerSingletonTests(unittest.TestCase):
    def test_get_hook_manager(self):
        from workflow_hooks import get_hook_manager
        hm1 = get_hook_manager()
        hm2 = get_hook_manager()
        self.assertIs(hm1, hm2)


if __name__ == "__main__":
    unittest.main()
