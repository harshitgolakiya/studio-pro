"""Local automation API — lightweight HTTP server for programmatic access.

Exposes Shadow Media Studio Pro's conversion pipeline over a local HTTP
endpoint so scripts, other tools, and CI/CD systems can convert images
without launching the GUI.

Endpoints:
  POST /convert         Convert a single file (multipart form or JSON path).
  POST /batch           Convert a list of files.
  GET  /formats         List supported input extensions and output formats.
  GET  /status          Server health check.
  POST /recipe/apply    Apply a named recipe to a conversion.

The server binds to 127.0.0.1 only and never accepts remote connections.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from converter import (
    SUPPORTED_EXTENSIONS,
    IMAGE_OUTPUT_FORMATS,
    convert_image,
    normalize_output_format,
)
from recipes import Recipe, list_recipes, load_recipe, coerce_settings

DEFAULT_PORT = 17394
DEFAULT_HOST = "127.0.0.1"


class _AutomationHandler(BaseHTTPRequestHandler):
    """Request handler for the local automation API."""

    server_version = "ShadowAutomationAPI/1.0"

    def log_message(self, format: str, *args: object) -> None:
        pass  # Suppress default stderr logging

    def _json_response(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._json_response({"error": message}, status)

    def _read_json_body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 4 * 1024 * 1024:
                return None
            data = json.loads(self.rfile.read(length))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/")

        if route == "/status":
            self._json_response({"status": "ok", "server": self.server_version})

        elif route == "/formats":
            self._json_response({
                "input_extensions": sorted(SUPPORTED_EXTENSIONS),
                "output_formats": {k: v[0] for k, v in IMAGE_OUTPUT_FORMATS.items()},
            })

        elif route == "/recipes":
            try:
                recipes = list_recipes()
                self._json_response({
                    "recipes": [{"name": r.name, "description": r.description} for r in recipes]
                })
            except Exception as e:
                self._error(500, str(e))

        elif route == "/studio/actions":
            from studio_actions import ACTION_LABELS
            from studio_workflows import WORKFLOWS
            from dataclasses import asdict
            self._json_response({"actions": ACTION_LABELS, "options": {k: [asdict(f) for f in d[2]] for k, d in WORKFLOWS.items()}})
        else:
            self._error(404, f"Unknown endpoint: {route}")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/")

        if route == "/convert":
            self._handle_convert()
        elif route == "/batch":
            self._handle_batch()
        elif route == "/recipe/apply":
            self._handle_recipe_apply()
        elif route == "/studio/run":
            body = self._read_json_body()
            if not isinstance(body, dict):
                self._error(400, "Provide a JSON action, sources, output_dir, and options")
                return
            try:
                from studio_actions import run_action
                result = run_action(body["action"], [Path(p) for p in body.get("sources", [])],
                                    Path(body["output_dir"]), options=body.get("options", {}), fmt=body.get("format"))
                self._json_response({"ok": result.ok, "outputs": [str(p) for p in result.outputs], "details": result.details}, 200 if result.ok else 422)
            except (ValueError, KeyError, TypeError) as exc:
                self._error(400, str(exc))
            except Exception as exc:
                self._error(500, str(exc))
        else:
            self._error(404, f"Unknown endpoint: {route}")

    def _handle_convert(self) -> None:
        body = self._read_json_body()
        if not body:
            self._error(400, "Request body must be JSON with 'source' and 'output_dir' fields.")
            return

        source = body.get("source")
        output_dir = body.get("output_dir")
        target_format = body.get("format", "WEBP")
        quality = int(body.get("quality", 80))
        lossless = bool(body.get("lossless", False))
        options = body.get("options", {})

        if not source or not output_dir:
            self._error(400, "Missing required 'source' and/or 'output_dir' fields.")
            return

        source_path = Path(source)
        if not source_path.is_file():
            self._error(404, f"Source file not found: {source}")
            return

        try:
            result = convert_image(
                source_path,
                Path(output_dir),
                target_format=normalize_output_format(target_format),
                quality=quality,
                lossless=lossless,
                **{k: v for k, v in options.items() if k not in ("source", "output_dir", "format", "quality", "lossless")},
            )
            self._json_response({
                "status": result.status,
                "source": str(result.source_path),
                "output": str(result.output_path) if result.output_path else None,
                "original_size": result.original_size,
                "output_size": result.output_size,
                "saved": result.saved,
                "error": result.error if hasattr(result, "error") else None,
            })
        except Exception as e:
            self._error(500, str(e))

    def _handle_batch(self) -> None:
        body = self._read_json_body()
        if not body:
            self._error(400, "Request body must be JSON with 'files' array and 'output_dir'.")
            return

        files = body.get("files", [])
        output_dir = body.get("output_dir")
        target_format = body.get("format", "WEBP")
        quality = int(body.get("quality", 80))

        if not files or not output_dir:
            self._error(400, "Missing 'files' array or 'output_dir'.")
            return

        results = []
        for f in files:
            source_path = Path(f)
            if not source_path.is_file():
                results.append({"source": str(f), "status": "Failed", "error": "File not found"})
                continue
            try:
                r = convert_image(
                    source_path,
                    Path(output_dir),
                    target_format=normalize_output_format(target_format),
                    quality=quality,
                )
                results.append({
                    "source": str(r.source_path),
                    "output": str(r.output_path) if r.output_path else None,
                    "status": r.status,
                    "original_size": r.original_size,
                    "output_size": r.output_size,
                })
            except Exception as e:
                results.append({"source": str(f), "status": "Failed", "error": str(e)})

        self._json_response({"results": results, "total": len(results)})

    def _handle_recipe_apply(self) -> None:
        body = self._read_json_body()
        if not body:
            self._error(400, "Request body must be JSON with 'recipe_name', 'source', and 'output_dir'.")
            return

        recipe_name = body.get("recipe_name", "")
        source = body.get("source")
        output_dir = body.get("output_dir")

        if not recipe_name or not source or not output_dir:
            self._error(400, "Missing 'recipe_name', 'source', or 'output_dir'.")
            return

        source_path = Path(source)
        if not source_path.is_file():
            self._error(404, f"Source file not found: {source}")
            return

        try:
            recipes = list_recipes()
            match = [r for r in recipes if r.name.lower() == recipe_name.lower()]
            if not match:
                self._error(404, f"Recipe not found: {recipe_name}")
                return
            recipe = match[0]
            settings = coerce_settings(recipe.settings)
            fmt = settings.get("target_format", "WEBP")
            quality = settings.get("quality", 80)

            result = convert_image(
                source_path,
                Path(output_dir),
                target_format=normalize_output_format(str(fmt)),
                quality=int(quality),
                **{k: v for k, v in settings.items() if k not in ("target_format", "quality")},
            )
            self._json_response({
                "recipe": recipe.name,
                "status": result.status,
                "source": str(result.source_path),
                "output": str(result.output_path) if result.output_path else None,
                "output_size": result.output_size,
            })
        except Exception as e:
            self._error(500, str(e))


class AutomationServer:
    """Local HTTP automation server for Shadow Media Studio Pro."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        if self.is_running:
            return
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("The automation API only binds to loopback")
        self._server = HTTPServer((self.host, self.port), _AutomationHandler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            try:
                server.shutdown()
            finally:
                # shutdown() stops serve_forever but intentionally does not
                # close the listening socket. Always release it so repeated
                # starts and test runs do not leak descriptors or hold ports.
                server.server_close()
        if thread is not None:
            thread.join(timeout=5)
