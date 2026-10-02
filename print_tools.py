"""Local print adapters, font inspection, PDF preflight, and ICC delivery."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile

from studio_runtime import StagedOutput, model_directory, resource_root, run_engine, check_cancel


def ghostscript_path():
    override = os.environ.get("SHADOW_GHOSTSCRIPT")
    if override and Path(override).is_file():
        return override
    root = resource_root() / "vendor" / "ghostscript"
    for name in ("bin/gswin64c.exe", "bin/gs", "gs"):
        if (root / name).is_file():
            return str(root / name)
    return shutil.which("gswin64c") or shutil.which("gs")


def _gs(source, destination, extra=None, cancel_check=None):
    engine = ghostscript_path()
    if not engine:
        raise RuntimeError("Ghostscript is missing. Run setup_print.py or set SHADOW_GHOSTSCRIPT.")
    resource_args = []
    if sys.platform == "darwin":
        share = resource_root() / "vendor" / "ghostscript" / "share"
        paths = [str(p) for p in share.rglob("*") if p.is_dir() and p.name in {"Init", "Font", "lib"}]
        if paths:
            resource_args = ["-I" + os.pathsep.join(paths)]
    run_engine([engine, "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
                *resource_args, *(extra or []), f"-sOutputFile={destination}", "-f", str(source.resolve())],
               timeout=600, cancel_check=cancel_check)


def import_design(source: Path, destination: Path, dpi=300, cancel_check=None):
    if source.suffix.lower() not in {".eps", ".ps", ".ai", ".indd", ".pdf"}:
        raise ValueError("Choose EPS, PS, AI, INDD, or PDF")
    if not source.is_file() or source.resolve() == destination.resolve():
        raise ValueError("Choose an existing input and a new PDF output")
    if not 72 <= dpi <= 1200:
        raise ValueError("Resolution must be 72-1200 DPI")
    check_cancel(cancel_check)
    with StagedOutput(destination) as stage:
        if source.suffix.lower() == ".indd":
            # INDD is proprietary. Use its owning application's automation interface,
            # or a supplied export alongside it; never pretend text reflow is layout import.
            sidecar = source.with_suffix(".pdf")
            if sidecar.is_file():
                from pypdf import PdfReader
                PdfReader(sidecar)
                shutil.copy2(sidecar, stage.path)
            elif sys.platform == "win32":
                try:
                    import win32com.client
                    import pythoncom
                    pythoncom.CoInitialize()
                    try:
                        app = win32com.client.Dispatch("InDesign.Application")
                        import json
                        script = ("var d=app.open(File(" + json.dumps(str(source.resolve())) + "));"
                                  "try { d.exportFile(ExportFormat.PDF_TYPE,File(" + json.dumps(str(stage.path)) + "),false); }"
                                  "finally { d.close(SaveOptions.NO); }")
                        app.DoScript(script, 1246973031)
                    finally:
                        pythoncom.CoUninitialize()
                except Exception as exc:
                    raise RuntimeError("INDD requires installed Adobe InDesign or a same-name PDF export beside the file. "
                                       "Export PDF from InDesign and retry.") from exc
            else:
                raise RuntimeError("Place the matching PDF export beside the INDD file before importing.")
        elif source.suffix.lower() in {".pdf", ".ai"} and source.read_bytes()[:1024].find(b"%PDF-") >= 0:
            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(source)
            writer = PdfWriter(clone_from=reader)
            try:
                writer.write(stage.path)
            finally:
                writer.close()
        else:
            _gs(source, stage.path, ["-dEPSCrop", f"-r{dpi}"], cancel_check)
        check_cancel(cancel_check)
    return stage.output


def inspect_fonts(source: Path):
    if source.suffix.lower() in {".ttf", ".otf", ".woff", ".woff2"}:
        from fontTools.ttLib import TTFont
        with TTFont(source) as font:
            names = {str(n.nameID): n.toUnicode() for n in font["name"].names if n.nameID in {1, 2, 4, 6, 13, 14}}
            return {"file": source.name, "names": names, "glyphs": len(font.getGlyphOrder()),
                    "embedding_flags": font["OS/2"].fsType if "OS/2" in font else None}
    from pypdf import PdfReader
    fonts = {}
    def visit(resources, seen):
        if not resources:
            return
        resources = resources.get_object()
        identity = id(resources)
        if identity in seen:
            return
        seen.add(identity)
        for name, ref in resources.get("/Font", {}).items():
            font = ref.get_object()
            descendants = font.get("/DescendantFonts", [])
            target = descendants[0].get_object() if descendants else font
            descriptor = target.get("/FontDescriptor")
            descriptor = descriptor.get_object() if descriptor else {}
            title = str(font.get("/BaseFont", name))
            fonts[title] = {"name": title, "type": str(font.get("/Subtype", "")),
                            "embedded": any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3"))}
        for ref in resources.get("/XObject", {}).values():
            obj = ref.get_object()
            if obj.get("/Subtype") == "/Form":
                visit(obj.get("/Resources"), seen)
    reader = PdfReader(source)
    for page in reader.pages:
        visit(page.get("/Resources"), set())
    return {"fonts": list(fonts.values())}


def pdf_preflight(source: Path, minimum_dpi=150):
    import pdfplumber
    if minimum_dpi <= 0:
        raise ValueError("Minimum image DPI must be positive")
    fonts = inspect_fonts(source)["fonts"]
    issues = [{"kind": "font_not_embedded", "font": f["name"]} for f in fonts if not f["embedded"]]
    pages = []
    with pdfplumber.open(source) as document:
        for index, page in enumerate(document.pages, 1):
            images = []
            for image in page.images:
                pixels = image.get("srcsize", (0, 0))
                dpi = min(pixels[0] * 72 / max(image["width"], .01), pixels[1] * 72 / max(image["height"], .01))
                images.append({"dpi": round(dpi), "colorspace": str(image.get("colorspace"))})
                if dpi < minimum_dpi:
                    issues.append({"kind": "low_resolution", "page": index, "dpi": round(dpi)})
            pages.append({"page": index, "width_points": page.width, "height_points": page.height, "images": images})
    return {"ok": not issues, "issues": issues, "fonts": fonts, "pages": pages,
            "scope": "Checks font embedding and image resolution; does not certify PDF/X, bleed, trapping, or press compliance."}


def cmyk_delivery(source: Path, destination: Path, profile: Path | None = None, dpi=300, cancel_check=None):
    from PIL import Image, ImageCms
    profile = profile or model_directory() / "color" / "default_cmyk.icc"
    if not profile.is_file():
        raise RuntimeError("Install the CMYK press profile in Models, or choose an ICC profile")
    if not 72 <= dpi <= 1200:
        raise ValueError("Delivery resolution must be 72-1200 DPI")
    check_cancel(cancel_check)
    with StagedOutput(destination) as stage:
        if source.suffix.lower() == ".pdf":
            _gs(source, stage.path, ["-sColorConversionStrategy=CMYK", "-dProcessColorModel=/DeviceCMYK",
                                    f"--permit-file-read={profile.resolve()}",
                                    f"-sOutputICCProfile={profile.resolve()}"], cancel_check)
        else:
            with Image.open(source) as image:
                if "A" in image.getbands():
                    rgba = image.convert("RGBA")
                    rgb = Image.new("RGB", rgba.size, "white")
                    rgb.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    rgb = image.convert("RGB")
                import io
                input_profile = ImageCms.ImageCmsProfile(io.BytesIO(image.info["icc_profile"])) if image.info.get("icc_profile") else ImageCms.createProfile("sRGB")
                # The source mode must match its profile; handle CMYK sources explicitly.
                if image.mode == "CMYK" and image.info.get("icc_profile"):
                    rgb = image
                cmyk = ImageCms.profileToProfile(rgb, input_profile, str(profile), outputMode="CMYK")
                cmyk.save(stage.path, format="TIFF", compression="tiff_lzw", dpi=(dpi, dpi), icc_profile=profile.read_bytes())
        check_cancel(cancel_check)
    return stage.output
