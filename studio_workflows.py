"""Definitions and dispatch for the complete agency tool collection."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from studio_runtime import StagedOutput, check_cancel


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    default: object = ""
    kind: str = "text"
    choices: tuple[str, ...] = ()


F = Field
PASSWORD = F("password", "Current PDF / archive password", "", "password")
PAGES = F("pages", "Pages (all or 1,3-5)", "all")
MAP = F("values", "Field values (JSON object)", "{}", "json")
REPLACE = F("replacements", "Find / replace pairs (JSON object)", "{}", "json")
LANGS = (F("source_language", "Source language code", "en"), F("target_language", "Target language code", "es"))

# action: (group, label, fields). Shared by forms and CLI help.
WORKFLOWS = {
    "pdf-protect": ("PDF", "Protect PDF", [F("open_password", "Open password", "", "password"), F("owner_password", "Owner password", "", "password"), PASSWORD, F("allow_printing", "Allow printing", True, "bool"), F("allow_copying", "Allow copying", False, "bool"), F("allow_editing", "Allow editing", False, "bool")]),
    "pdf-unlock": ("PDF", "Unlock PDF", [PASSWORD]),
    "pdf-redact": ("PDF", "Redact text / regions", [F("terms", "Text or patterns to remove (one per line)", "", "lines"), F("regions", "Regions [page,left,top,right,bottom] (JSON array)", "[]", "json"), PAGES, PASSWORD, F("regex", "Use regular expressions", False, "bool"), F("match_case", "Match case", False, "bool")]),
    "pdf-fields": ("PDF", "Inspect form fields", [PASSWORD]),
    "pdf-fill": ("PDF", "Fill form", [MAP, PASSWORD, F("flatten", "Flatten fields into pages", False, "bool")]),
    "pdf-identity": ("PDF", "Create signing identity", [F("name", "Signer name"), F("organization", "Organization"), F("email", "Email"), F("passphrase", "Identity passphrase (6+ characters)", "", "password")]),
    "pdf-sign": ("PDF", "Sign PDF", [F("identity", "Signing identity (.p12/.pfx)", "", "file"), F("passphrase", "Identity passphrase", "", "password"), F("reason", "Signing reason"), F("location", "Location")]),
    "pdf-signatures": ("PDF", "Verify PDF signatures", []),
    "pdf-repair": ("PDF", "Repair PDF", [PASSWORD]),
    "pdf-tables": ("PDF", "Extract PDF tables", [F("format", "Output format", "XLSX", choices=("XLSX", "CSV", "JSON")), PAGES, PASSWORD]),
    "office-replace": ("Office", "Find and replace", [REPLACE, F("match_case", "Match case", False, "bool"), F("whole_word", "Whole words", False, "bool"), F("regex", "Regular expressions", False, "bool")]),
    "office-properties": ("Office", "Inspect document properties", []),
    "office-set-properties": ("Office", "Update document properties", [F("properties", "Properties: title, author, subject, keywords, comments, category", "{}", "json")]),
    "office-edit": ("Office", "Open visual Office editor", []),
    "data-schema": ("Data", "Infer data schema", [F("sheet", "Workbook sheet (optional)")]),
    "data-validate": ("Data", "Validate data against schema", [F("schema", "JSON schema file", "", "file"), F("sheet", "Workbook sheet (optional)")]),
    "subtitle-edit": ("Subtitles", "Edit subtitle timing and text", [F("format", "Output format", "SRT", choices=("SRT", "VTT", "TXT", "JSON")), F("shift", "Time offset (seconds)", 0.0, "float"), F("scale", "Timing scale", 1.0, "float"), F("max_chars", "Characters per line", 42, "int"), F("max_lines", "Lines per cue", 2, "int"), F("merge_short", "Merge short cues", False, "bool"), REPLACE, F("speaker_names", "Speaker names (JSON object)", "{}", "json")]),
    "subtitle-translate": ("Subtitles", "Translate subtitles", [F("format", "Output format", "SRT", choices=("SRT", "VTT")), *LANGS]),
    "text-translate": ("Subtitles", "Translate text / Markdown", list(LANGS)),
    "speech-batch": ("Speech", "Batch transcription / speaker labels", [F("format", "Output format", "SRT", choices=("TXT", "SRT", "VTT", "JSON")), F("model_path", "Whisper model folder (optional)", "", "folder"), F("language", "Language code (empty = detect)", ""), F("translate", "Translate speech to English", False, "bool"), F("speakers", "Label speakers", False, "bool"), F("speaker_count", "Speaker count (0 = detect)", 0, "int")]),
    "audio-isolate": ("Speech", "Isolate speech", [F("format", "Output format", "WAV", choices=("WAV", "MP3", "FLAC", "AAC", "OPUS")), F("normalize", "Normalize loudness", True, "bool")]),
    "archive-inspect": ("Delivery", "Inspect archive", [PASSWORD]),
    "folder-manifest": ("Delivery", "Write folder manifest / checksums", []),
    "folder-verify": ("Delivery", "Verify folder manifest", []),
    "print-import": ("Print", "Import EPS / AI / InDesign", [F("dpi", "Raster resolution (DPI)", 300, "int")]),
    "print-fonts": ("Print", "Inspect PDF or font file", []),
    "print-preflight": ("Print", "PDF print preflight", [F("minimum_dpi", "Minimum image resolution", 150, "int")]),
    "print-cmyk": ("Print", "CMYK delivery", [F("profile", "Press ICC profile (optional)", "", "file"), F("dpi", "Image delivery resolution", 300, "int")]),
    "project-delivery": ("Projects", "Run saved project delivery", [F("profile", "Project profile file", "", "file"), F("package", "Create delivery ZIP", True, "bool")]),
    "publish-file": ("Integrations", "Publish through an adapter", [F("adapter", "Publishing adapter", "Local web project", choices=("Local web project", "Cloud storage", "WordPress", "Design export folder", "Plugin exporter")), F("config", "Adapter configuration (JSON object)", "{}", "json")]),
    "plugin-codec": ("Integrations", "Convert with a plugin codec", [F("name", "Loaded codec name"), F("extension", "Output extension", ".png")]),
    "plugin-process": ("Integrations", "Apply plugin processor", [F("name", "Loaded processor name"), F("parameters", "Processor parameters (JSON object)", "{}", "json")]),
}


def coerce_options(action, options):
    fields = {field.key: field for field in WORKFLOWS[action][2]}
    unknown = set(options) - set(fields)
    if unknown:
        raise ValueError(f"Unknown options for {action}: {', '.join(sorted(unknown))}")
    result = {}
    for key, field in fields.items():
        value = options.get(key, field.default)
        if field.kind == "json":
            value = json.loads(value) if isinstance(value, str) else value
            if key == "regions":
                if not isinstance(value, list):
                    raise ValueError("Regions must be a JSON array")
            elif not isinstance(value, dict):
                raise ValueError(f"{field.label} must be a JSON object")
        elif field.kind == "lines":
            value = value.splitlines() if isinstance(value, str) else value
        elif field.kind == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"{field.label} must be true or false")
        elif field.kind in {"int", "float"}:
            value = int(value) if field.kind == "int" else float(value)
        else:
            value = str(value)
        if field.choices and value not in field.choices:
            raise ValueError(f"Choose {', '.join(field.choices)} for {field.label}")
        result[key] = value
    return result


def run_workflow(action, sources, output_dir, options=None, cancel_check=None, progress=None):
    from studio_actions import StudioResult
    opts = coerce_options(action, options or {})
    check_cancel(cancel_check)
    if action != "pdf-identity" and (not sources or any(not p.exists() for p in sources)):
        raise ValueError("Choose existing inputs")
    if action not in {"pdf-identity", "speech-batch", "project-delivery"} and len(sources) != 1:
        raise ValueError("Choose one input for this action")
    source = sources[0] if sources else Path("signer")
    output_dir = Path(output_dir)
    def dest(extension, suffix=None):
        return output_dir / f"{source.stem}-{suffix or action}{extension}"
    def report(details, ok=True):
        with StagedOutput(dest(".json")) as stage:
            stage.path.write_text(json.dumps(details, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return StudioResult([stage.output], details if isinstance(details, dict) else {"items": details}, ok)
    if action == "project-delivery":
        from agency_projects import load_profile, run_project
        profile = load_profile(opts['profile'])
        if profile.get('export_set','Single preset') != 'Single preset':
            from campaign_exports import run_campaign
            return run_campaign(profile,sources,output_dir,opts['package'],cancel_check,progress)
        return run_project(profile, sources, output_dir, opts["package"], cancel_check, progress)
    if action == "publish-file":
        from agency_integrations import publish_file
        details = publish_file(opts["adapter"], source, opts["config"])
        return report(details, details.get("status") == "published")
    if action in {"plugin-codec", "plugin-process"}:
        from plugin_sdk import get_registry
        from agency_integrations import load_plugins
        load_plugins()
        registry = get_registry()
        plugins = registry.codecs if action == "plugin-codec" else registry.processors
        plugin = next((p for p in plugins if p.name == opts["name"]), None)
        if not plugin:
            raise ValueError("Install the named plugin in the plugins folder")
        from PIL import Image
        if action == "plugin-codec":
            extension = opts["extension"].lower()
            if not extension.startswith(".") or extension not in plugin.extensions_out:
                raise ValueError("Choose one of the codec's supported output extensions")
            image = plugin.decode(source)
        else:
            extension = ".png"
            with Image.open(source) as original:
                image = plugin.process(original.copy(), **opts["parameters"])
        try:
            with StagedOutput(dest(extension)) as stage:
                if action == "plugin-codec":
                    plugin.encode(image, stage.path)
                else:
                    image.save(stage.path, format="PNG")
        finally:
            image.close()
        return StudioResult([stage.output])
    if action.startswith("pdf-"):
        import pdf_advanced as pdf
        if action == "pdf-protect":
            opts["current_password"] = opts.pop("password") or None
            path = pdf.protect_pdf(source, dest(".pdf"), **opts)
        elif action == "pdf-unlock":
            path = pdf.unlock_pdf(source, dest(".pdf"), **opts)
        elif action == "pdf-redact":
            path, count = pdf.redact_pdf(source, dest(".pdf"), **opts, cancel_check=cancel_check, progress=progress)
            return StudioResult([path], {"redactions": count})
        elif action == "pdf-fields":
            return report(pdf.list_form_fields(source, **opts))
        elif action == "pdf-fill":
            path = pdf.fill_form(source, dest(".pdf"), **opts)
        elif action == "pdf-identity":
            path = pdf.create_signing_identity(destination=dest(".p12"), **opts)
        elif action == "pdf-sign":
            opts["identity"] = Path(opts["identity"])
            path = pdf.sign_pdf(source, dest(".pdf"), **opts)
        elif action == "pdf-signatures":
            items = pdf.verify_signatures(source)
            return report(items, bool(items) and all(p["intact"] and p["valid"] for p in items))
        elif action == "pdf-repair":
            path, pages = pdf.repair_pdf(source, dest(".pdf"), **opts)
            return StudioResult([path], {"pages_recovered": pages})
        else:
            fmt = opts.pop("format")
            path, count = pdf.extract_tables(source, dest("." + fmt.lower()), **opts, cancel_check=cancel_check, progress=progress)
            return StudioResult([path], {"tables": count})
        return StudioResult([path])
    if action.startswith("office-"):
        import office_edit as office
        if action == "office-edit":
            office.open_in_editor(source)
            return StudioResult(details={"opened": str(source)})
        if action == "office-properties":
            return report(office.read_properties(source, cancel_check))
        destination = dest(office.editable_extension(source))
        if action == "office-replace":
            path, count = office.replace_text(source, destination, **opts, cancel_check=cancel_check)
            return StudioResult([path], {"replacements": count})
        return StudioResult([office.write_properties(source, destination, **opts, cancel_check=cancel_check)])
    if action.startswith("data-"):
        from data_tools import load_records, infer_schema, validate_data
        if action == "data-schema":
            return report(infer_schema(load_records(source, opts["sheet"] or None)))
        problems = validate_data(source, Path(opts["schema"]), sheet=opts["sheet"] or None)
        return report({"valid": not problems, "problems": problems}, not problems)
    if action.startswith("subtitle-"):
        from subtitle_tools import edit_subtitles
        fmt = opts.pop("format")
        if action == "subtitle-translate":
            opts = {"translate": (opts["source_language"], opts["target_language"])}
        path, details = edit_subtitles(source, dest("." + fmt.lower()), **opts, cancel_check=cancel_check, progress=progress)
        return StudioResult([path], details)
    if action == "text-translate":
        from subtitle_tools import translate_text_file
        return StudioResult([translate_text_file(source, dest(source.suffix), **opts, cancel_check=cancel_check, progress=progress)])
    if action == "speech-batch":
        from speech_engine import transcribe_batch
        opts["fmt"] = opts.pop("format")
        opts["model_path"] = Path(opts["model_path"]) if opts["model_path"] else None
        opts["language"] = opts["language"] or None
        opts["speaker_count"] = opts["speaker_count"] or None
        results = transcribe_batch(sources, output_dir, cancel_check=cancel_check, progress=progress, **opts)
        details = {"files": [{"source": str(r.source_path), "status": r.status, "error": r.error} for r in results]}
        return StudioResult([r.output_path for r in results if r.output_path], details, all(r.status == "Completed" for r in results))
    if action == "audio-isolate":
        from audio_tools import ENCODERS, process_audio
        fmt = opts.pop("format")
        return StudioResult([process_audio(source, dest(ENCODERS[fmt][0]), fmt=fmt, isolate_voice=True, **opts, cancel_check=cancel_check)])
    if action in {"archive-inspect", "folder-manifest", "folder-verify"}:
        from archive_tools import inspect_archive, write_folder_manifest, verify_folder
        if action == "archive-inspect":
            details = inspect_archive(source, opts["password"] or None)
            return report(details, not details["problems"])
        if action == "folder-manifest":
            return StudioResult([write_folder_manifest(source, cancel_check=cancel_check, progress=progress)])
        details = verify_folder(source, cancel_check)
        return report(details, details["ok"])
    from print_tools import import_design, inspect_fonts, pdf_preflight, cmyk_delivery
    if action == "print-import":
        return StudioResult([import_design(source, dest(".pdf"), cancel_check=cancel_check, **opts)])
    if action == "print-fonts":
        return report(inspect_fonts(source))
    if action == "print-preflight":
        details = pdf_preflight(source, **opts)
        return report(details, details["ok"])
    opts["profile"] = Path(opts["profile"]) if opts["profile"] else None
    return StudioResult([cmyk_delivery(source, dest(".pdf" if source.suffix.lower() == ".pdf" else ".tif"), cancel_check=cancel_check, **opts)])
