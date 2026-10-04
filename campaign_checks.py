"""Read-only delivery checks against a campaign's recorded export requirements."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from PIL import Image
from campaign_crops import SOCIAL_SIZES, crop_box
from studio_runtime import check_cancel, StagedOutput, run_engine


def delivery_rules(profile):
    rules = profile.get('delivery_rules', {})
    if not isinstance(rules, dict):
        raise ValueError('Delivery limits must be an object')
    limit = rules.get('max_file_mb', 25)
    if type(limit) not in (int, float) or not math.isfinite(limit) or not 0 <= limit <= 1000000:
        raise ValueError('Maximum file size must be between 0 and 1000000 MB')
    return {'max_file_mb': limit}


def _sha(path, cancel_check=None):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            check_cancel(cancel_check)
            digest.update(block)
    return digest.hexdigest()


def _inside(folder, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('Invalid delivery output path')
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder) or path == folder:
        raise ValueError('Delivery output must stay inside its campaign folder')
    return path


def check_delivery(receipt_path, rules=None, cancel_check=None, progress=None):
    from campaign_exports import EXPORT_SETS
    from agency_projects import validate_profile
    receipt_path = Path(receipt_path).resolve()
    folder = receipt_path.parent
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('version') != 1 or not isinstance(receipt.get('jobs'), list) or not receipt['jobs']:
        raise ValueError('Invalid or empty campaign receipt')
    validate_profile(receipt.get('profile', {}))
    rules = delivery_rules({'delivery_rules': rules}) if rules is not None else delivery_rules(receipt.get('profile', {}))
    rows = []
    issues = []
    groups = defaultdict(list)
    paths = set()
    for index, job in enumerate(receipt['jobs'], 1):
        check_cancel(cancel_check)
        if not isinstance(job, dict):
            raise ValueError('Invalid campaign job')
        path = _inside(folder, job.get('relative_output'))
        if progress:
            progress(f'Checking {index}/{len(receipt["jobs"])}: {path.name}')
        row = {'file': job['relative_output'], 'preset': job.get('preset', ''), 'issues': []}
        rows.append(row)
        def issue(level, text):
            row['issues'].append({'level': level, 'text': text})
        if str(path).casefold() in paths:
            issue('error', 'Two required exports point to the same file.')
        paths.add(str(path).casefold())
        groups[job.get('source', '')].append(job.get('preset'))
        if job.get('status') != 'completed':
            issue('error', 'Required export is unfinished. Retry the campaign export.')
        if not path.is_file():
            issue('error', 'Required file is missing.')
            continue
        before = path.stat()
        row['bytes'] = before.st_size
        if not before.st_size:
            issue('error', 'The file is empty.')
            continue
        if _sha(path, cancel_check) != job.get('output_sha256'):
            issue('error', 'File contents changed after export. Create a new export.')
        if rules['max_file_mb'] and before.st_size > rules['max_file_mb'] * 1024 * 1024:
            issue('warning', f'File exceeds the configured {rules["max_file_mb"]:g} MB limit.')
        preset = job.get('preset')
        if preset in {'Web images', 'Print images', *SOCIAL_SIZES}:
            try:
                with Image.open(path) as image:
                    row['dimensions'] = list(image.size)
                    expected = 'JPEG' if preset in SOCIAL_SIZES else 'WEBP' if preset == 'Web images' else 'TIFF'
                    if image.format != expected:
                        issue('error', f'Expected {expected}; found {image.format or "unknown format"}.')
                    if preset in SOCIAL_SIZES and image.size != SOCIAL_SIZES[preset]:
                        size = SOCIAL_SIZES[preset]
                        issue('error', f'Expected {size[0]} × {size[1]} pixels; found {image.width} × {image.height}.')
                    if preset == 'Web images' and max(image.size)>1920:
                        issue('error', 'Web image exceeds the preset maximum of 1920 pixels.')
                    image.verify()
                # Decode too: valid headers alone do not guarantee usable pixel data.
                with Image.open(path) as image:
                    image.load()
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                issue('error', f'Image could not be read: {str(exc)[:160]}')
            if preset in SOCIAL_SIZES and job.get('source'):
                try:
                    with Image.open(job['source']) as original:
                        width, height = original.size
                        if original.getexif().get(274) in (5,6,7,8):width,height=height,width
                    settings = receipt.get('profile', {}).get('settings', {})
                    if str(settings.get('rotate_angle', '0°')) in ('90°', '270°'):
                        width, height = height, width
                    box = crop_box((width, height), SOCIAL_SIZES[preset])
                    if box[2] - box[0] < SOCIAL_SIZES[preset][0] or box[3] - box[1] < SOCIAL_SIZES[preset][1]:
                        issue('warning', 'Source resolution may require enlargement for this crop. Inspect sharpness before handoff.')
                except (OSError, ValueError, Image.DecompressionBombError):
                    issue('warning', 'Source resolution could not be checked; inspect export sharpness.')
        elif preset == 'Client documents':
            try:
                import pypdfium2 as pdfium
                document = pdfium.PdfDocument(path)
                try:
                    row['pages'] = len(document)
                    if not row['pages']:
                        issue('error', 'The PDF contains no pages.')
                finally:
                    document.close()
            except Exception:
                issue('error', 'The PDF could not be opened.')
        elif preset in {'Video delivery', 'Audio master'}:
            from media_engine import get_ffprobe_path
            probe = get_ffprobe_path()
            if not probe:
                issue('warning', 'Media inspection engine is unavailable; playback must be checked manually.')
            else:
                try:
                    media = json.loads(run_engine([probe, '-v', 'error', '-show_entries', 'stream=codec_type:format=format_name', '-of', 'json', str(path)], timeout=30, cancel_check=cancel_check))
                    required = 'video' if preset == 'Video delivery' else 'audio'
                    if not any(stream.get('codec_type') == required for stream in media.get('streams', [])):
                        issue('error', f'No {required} stream was found.')
                    expected_format = 'mp4' if required == 'video' else 'wav'
                    if expected_format not in media.get('format', {}).get('format_name', '').split(','):
                        issue('error', f'Expected a {expected_format.upper()} container.')
                except (RuntimeError, ValueError, TimeoutError):
                    issue('error', 'Media could not be inspected; verify playback or export again.')
        else:
            issue('error', 'Unknown delivery preset; format requirements could not be checked.')
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            issue('error', 'File changed during checking. Run delivery checks again.')
    required = EXPORT_SETS.get(receipt.get('profile', {}).get('export_set', 'Single preset'), ())
    for presets in groups.values():
        missing = set(required) - set(presets)
        if missing:
            issues.append({'level': 'error', 'text': 'Required variants are missing from the receipt: ' + ', '.join(sorted(missing))})
    if receipt.get('archive'):
        archive = _inside(folder, receipt['archive'])
        if not archive.is_file() or _sha(archive, cancel_check) != receipt.get('archive_sha256'):
            issues.append({'level': 'error', 'text': 'The delivery ZIP is missing or changed. Create a new export.'})
    all_issues = issues + [issue for row in rows for issue in row['issues']]
    errors = sum(issue['level'] == 'error' for issue in all_issues)
    warnings = sum(issue['level'] == 'warning' for issue in all_issues)
    return {'version': 1, 'checked': datetime.now(timezone.utc).isoformat(), 'status': 'Needs attention' if errors else 'Ready with warnings' if warnings else 'Ready',
            'errors': errors, 'warnings': warnings, 'files': len(rows), 'rules': rules, 'issues': issues, 'results': rows}


def save_check_report(report, destination):
    with StagedOutput(Path(destination), overwrite=True) as stage:
        stage.path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return stage.output
