"""Integrations for design and publishing workflows.

Provides adaptors that bridge Shadow Media Studio Pro's conversion
pipeline with common design-tool and publishing-platform outputs:

  - **Figma asset export**  – Watch a Figma-export directory and convert.
  - **WordPress media**     – Upload converted images via WP REST API.
  - **Shopify product**     – Upload product images via Shopify Admin API.
  - **S3 / GCS bucket**     – Upload to cloud storage.
  - **Local web project**   – Copy to a ``public/images`` tree with manifests.
  - **Sketch / Adobe XD**   – Watch exported-asset folders.

Each integration is a simple class that can be used standalone or
registered with the plugin SDK as an :class:`ExporterPlugin`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base integration
# ---------------------------------------------------------------------------

class Integration(ABC):
    """Base class for all integrations."""

    name: str = "Base Integration"
    description: str = ""

    @abstractmethod
    def publish(self, source: Path, output: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        """Publish the converted file and return status metadata."""
        ...

    def validate_config(self) -> list[str]:
        """Return a list of configuration errors (empty = valid)."""
        return []


# ---------------------------------------------------------------------------
# Local web project integration
# ---------------------------------------------------------------------------

@dataclass
class LocalWebProjectIntegration(Integration):
    """Copy converted images into a local web project with a manifest."""

    name: str = "Local Web Project"
    description: str = "Copy images to a web project's assets directory with a JSON manifest"
    project_root: Path = field(default_factory=lambda: Path("."))
    assets_dir: str = "public/images"
    manifest_name: str = "image-manifest.json"
    base_url: str = "/images/"

    def publish(self, source: Path, output: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        dest_dir = self.project_root / self.assets_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_file = dest_dir / output.name
        shutil.copy2(output, dest_file)

        # Update manifest
        manifest_path = dest_dir / self.manifest_name
        manifest: dict[str, Any] = {}
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        manifest.setdefault("images", {})
        manifest["images"][output.stem] = {
            "filename": output.name,
            "url": self.base_url + output.name,
            "format": output.suffix.lstrip(".").upper(),
            "size_bytes": output.stat().st_size,
            "source": source.name,
            "converted_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2), "utf-8")

        return {
            "status": "published",
            "destination": str(dest_file),
            "url": self.base_url + output.name,
        }

    def validate_config(self) -> list[str]:
        errors = []
        if not self.project_root.is_dir():
            errors.append(f"Project root not found: {self.project_root}")
        return errors


# ---------------------------------------------------------------------------
# Cloud storage integration (S3-compatible / GCS)
# ---------------------------------------------------------------------------

@dataclass
class CloudStorageIntegration(Integration):
    """Upload converted images to S3-compatible or GCS buckets.

    Requires appropriate credentials in the environment. Uses the
    cloud provider's SDK if available; falls back to CLI tools.
    """

    name: str = "Cloud Storage"
    description: str = "Upload images to S3/GCS/Azure Blob Storage"
    provider: str = "s3"  # "s3" | "gcs" | "azure"
    bucket: str = ""
    prefix: str = "images/"
    region: str = ""

    def publish(self, source: Path, output: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        key = f"{self.prefix}{output.name}"
        if self.provider == "s3":
            return self._upload_s3(output, key)
        elif self.provider == "gcs":
            return self._upload_gcs(output, key)
        elif self.provider == "azure":
            return self._upload_azure(output, key)
        else:
            return {"status": "error", "error": f"Unknown provider: {self.provider}"}

    def _upload_s3(self, output: Path, key: str) -> dict[str, Any]:
        try:
            import boto3  # type: ignore
            s3 = boto3.client("s3", region_name=self.region or None)
            content_type = _guess_content_type(output)
            s3.upload_file(str(output), self.bucket, key,
                           ExtraArgs={"ContentType": content_type})
            url = f"https://{self.bucket}.s3.amazonaws.com/{key}"
            return {"status": "published", "url": url, "key": key}
        except ImportError:
            return {"status": "error", "error": "boto3 not installed"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _upload_gcs(self, output: Path, key: str) -> dict[str, Any]:
        try:
            from google.cloud import storage as gcs  # type: ignore
            client = gcs.Client()
            bucket = client.bucket(self.bucket)
            blob = bucket.blob(key)
            blob.upload_from_filename(str(output))
            return {"status": "published", "url": blob.public_url, "key": key}
        except ImportError:
            return {"status": "error", "error": "google-cloud-storage not installed"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _upload_azure(self, output: Path, key: str) -> dict[str, Any]:
        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore
            conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
            client = BlobServiceClient.from_connection_string(conn_str)
            container = client.get_container_client(self.bucket)
            with open(output, "rb") as f:
                container.upload_blob(key, f, overwrite=True)
            return {"status": "published", "key": key}
        except ImportError:
            return {"status": "error", "error": "azure-storage-blob not installed"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def validate_config(self) -> list[str]:
        errors = []
        if not self.bucket:
            errors.append("Bucket name is required")
        if self.provider not in ("s3", "gcs", "azure"):
            errors.append(f"Unknown provider: {self.provider}")
        return errors


# ---------------------------------------------------------------------------
# WordPress REST API integration
# ---------------------------------------------------------------------------

@dataclass
class WordPressIntegration(Integration):
    """Upload converted images to a WordPress site via REST API."""

    name: str = "WordPress"
    description: str = "Upload images to WordPress Media Library"
    site_url: str = ""
    username: str = ""
    app_password: str = ""

    def publish(self, source: Path, output: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        try:
            import requests  # type: ignore
        except ImportError:
            return {"status": "error", "error": "requests library not installed"}

        api_url = urljoin(self.site_url.rstrip("/") + "/", "wp-json/wp/v2/media")
        content_type = _guess_content_type(output)

        try:
            with open(output, "rb") as f:
                resp = requests.post(
                    api_url,
                    headers={
                        "Content-Disposition": f'attachment; filename="{output.name}"',
                        "Content-Type": content_type,
                    },
                    data=f,
                    auth=(self.username, self.app_password),
                    timeout=60,
                )
            if resp.status_code in (200, 201):
                data = resp.json()
                return {
                    "status": "published",
                    "id": data.get("id"),
                    "url": data.get("source_url"),
                }
            return {"status": "error", "code": resp.status_code, "error": resp.text[:200]}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def validate_config(self) -> list[str]:
        errors = []
        if not self.site_url:
            errors.append("WordPress site URL is required")
        if not self.username or not self.app_password:
            errors.append("Username and application password are required")
        return errors


# ---------------------------------------------------------------------------
# Design tool watch integration
# ---------------------------------------------------------------------------

@dataclass
class DesignToolWatchIntegration(Integration):
    """Watch a directory for exported design-tool assets and auto-convert."""

    name: str = "Design Tool Watch"
    description: str = "Watch Figma/Sketch/XD export folders for new assets"
    watch_dir: Path = field(default_factory=lambda: Path("."))
    output_dir: Path = field(default_factory=lambda: Path("."))
    tool: str = "figma"  # "figma" | "sketch" | "xd" | "generic"
    auto_convert_format: str = "WEBP"
    auto_convert_quality: int = 80

    def publish(self, source: Path, output: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        """For design-tool integration, 'publish' copies to the output dir."""
        dest = self.output_dir / output.name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output, dest)
        return {"status": "published", "destination": str(dest), "tool": self.tool}

    def get_watch_patterns(self) -> list[str]:
        """Return file patterns to watch based on the design tool."""
        patterns = {
            "figma": ["*.png", "*.svg", "*.jpg", "*.pdf"],
            "sketch": ["*.png", "*.svg", "*.jpg", "*.pdf", "*.tiff"],
            "xd": ["*.png", "*.svg", "*.jpg"],
            "generic": ["*.png", "*.jpg", "*.jpeg", "*.svg", "*.tiff", "*.bmp"],
        }
        return patterns.get(self.tool, patterns["generic"])

    def validate_config(self) -> list[str]:
        errors = []
        if not self.watch_dir.is_dir():
            errors.append(f"Watch directory not found: {self.watch_dir}")
        return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _guess_content_type(path: Path) -> str:
    """Guess MIME type from file extension."""
    types = {
        ".webp": "image/webp",
        ".avif": "image/avif",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".jxl": "image/jxl",
        ".jp2": "image/jp2",
        ".psd": "image/vnd.adobe.photoshop",
    }
    return types.get(path.suffix.lower(), "application/octet-stream")


# ---------------------------------------------------------------------------
# Registry helper
# ---------------------------------------------------------------------------

def list_integrations() -> list[type[Integration]]:
    """Return all available integration classes."""
    return [
        LocalWebProjectIntegration,
        CloudStorageIntegration,
        WordPressIntegration,
        DesignToolWatchIntegration,
    ]
