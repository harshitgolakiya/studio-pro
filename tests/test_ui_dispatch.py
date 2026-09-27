from __future__ import annotations

import threading
import unittest

from ui_dispatch import TkEventBridge


class _FakeRoot:
    def __init__(self) -> None:
        self.callbacks: dict[str, object] = {}
        self.cancelled: list[str] = []
        self._next = 0

    def after(self, _delay: int, callback: object) -> str:
        self._next += 1
        key = f"after-{self._next}"
        self.callbacks[key] = callback
        return key

    def after_cancel(self, key: str) -> None:
        self.cancelled.append(key)
        self.callbacks.pop(key, None)

    def report_callback_exception(self, *_args: object) -> None:
        raise AssertionError("callback should not fail")


class TkEventBridgeTests(unittest.TestCase):
    def test_worker_post_runs_only_when_main_thread_drains(self) -> None:
        root = _FakeRoot()
        bridge = TkEventBridge(root)  # type: ignore[arg-type]
        calls: list[int] = []
        worker = threading.Thread(target=lambda: bridge.post(lambda: calls.append(1)))
        worker.start()
        worker.join()
        self.assertEqual(calls, [])

        first = next(iter(root.callbacks.values()))
        first()  # type: ignore[operator]
        self.assertEqual(calls, [1])
        bridge.close()

    def test_close_discards_pending_callbacks(self) -> None:
        root = _FakeRoot()
        bridge = TkEventBridge(root)  # type: ignore[arg-type]
        worker = threading.Thread(target=lambda: bridge.post(lambda: self.fail("ran after close")))
        worker.start()
        worker.join()
        bridge.close()
        self.assertTrue(root.cancelled)
        self.assertFalse(bridge.post(lambda: None))


if __name__ == "__main__":
    unittest.main()
