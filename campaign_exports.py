"""Local campaign export sets with a durable per-output retry receipt."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid

from agency_projects import PRESETS, delivery_name, validate_profile
from studio_runtime import StagedOutput, StudioCancelled, check_cancel

EXPORT_SETS = {
    'Single preset': (),
    'Social image set': ('Social square', 'Social portrait', 'Social story'),
    'Web + social images': ('Web images', 'Social square', 'Social portrait', 'Social story'),
    'Mixed client handoff': (),
}


def plan_exports(profile, sources):
    from headless_cli import _paths
    from converter import SUPPORTED_EXTENSIONS
    from doc_converter import SUPPORTED_DOCUMENT_EXTENSIONS
    from media_engine import SUPPORTED_AUDIO_EXTENSIONS, SUPPORTED_VIDEO_EXTENSIONS
    validate_profile(profile)
    bundle = profile.get('export_set', 'Single preset')
    if bundle not in EXPORT_SETS:raise ValueError('Choose a supported export set')
    for source in sources:
        if not Path(source).exists():raise ValueError(f'Input no longer exists: {source}')
        supported=SUPPORTED_EXTENSIONS|SUPPORTED_DOCUMENT_EXTENSIONS|SUPPORTED_AUDIO_EXTENSIONS|SUPPORTED_VIDEO_EXTENSIONS
        if Path(source).is_file() and Path(source).suffix.lower() not in supported:raise ValueError(f'Unsupported campaign input: {Path(source).name}')
    paths = list(dict.fromkeys(path.resolve() for path in _paths([str(p) for p in sources])))
    if not paths:raise ValueError('Choose supported files or a folder containing supported files')
    jobs = [];names = set()
    for index, source in enumerate(paths, 1):
        ext = source.suffix.lower()
        if bundle == 'Mixed client handoff':
            presets = ('Client documents',) if ext in SUPPORTED_DOCUMENT_EXTENSIONS else ('Audio master',) if ext in SUPPORTED_AUDIO_EXTENSIONS else ('Video delivery',) if ext in SUPPORTED_VIDEO_EXTENSIONS else ('Web images',)
        else:presets = EXPORT_SETS[bundle] or (profile.get('preset', 'Web images'),)
        for preset in presets:
            image_preset = preset in {'Web images','Social square','Social portrait','Social story','Print images'}
            compatible = (ext in SUPPORTED_EXTENSIONS if image_preset else
                          ext in SUPPORTED_DOCUMENT_EXTENSIONS if preset == 'Client documents' else
                          ext in SUPPORTED_AUDIO_EXTENSIONS if preset == 'Audio master' else
                          ext in SUPPORTED_VIDEO_EXTENSIONS if preset == 'Video delivery' else True)
            if not compatible:raise ValueError(f'{source.name} cannot use {preset}. Choose a matching preset or Mixed client handoff.')
            if preset == 'Current queue settings':raise ValueError('Choose an explicit delivery preset to preview campaign outputs')
            suffix = {'WEBP':'.webp','JPG':'.jpg','TIFF':'.tiff','PDF':'.pdf','WAV':'.wav','MP4':'.mp4'}[PRESETS[preset]['target_format']]
            variant = preset.lower().replace(' ', '-')
            name = delivery_name({**profile,'preset':preset}, source, index)
            candidate = f'{variant}/{name}{suffix}';counter=2
            while candidate.casefold() in names:
                candidate=f'{variant}/{name}-{counter}{suffix}';counter+=1
            names.add(candidate.casefold())
            jobs.append({'source':str(source),'preset':preset,'relative_output':candidate})
    return jobs


def _sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream, 'sha256').hexdigest()


def _write(path, receipt):
    with StagedOutput(path, overwrite=True) as stage:
        stage.path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding='utf-8')


def run_campaign(profile, sources, output_dir, package=True, cancel_check=None, progress=None, retry_receipt=None):
    from agency_projects import run_project
    from archive_tools import build_delivery_package
    from studio_actions import StudioResult
    if retry_receipt:
        receipt_path = Path(retry_receipt).resolve()
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt.get('version') != 1 or not isinstance(receipt.get('jobs'), list):raise ValueError('Invalid campaign receipt')
        folder = receipt_path.parent
        profile = validate_profile(receipt['profile'])
        package = receipt['package']
        if receipt.get('archive') and not (folder/receipt['archive']).resolve().is_relative_to(folder):raise ValueError('Invalid campaign archive path')
        if receipt.get('archive'):
            archive=folder/receipt['archive']
            if not archive.is_file() or _sha(archive)!=receipt.get('archive_sha256'):raise ValueError('The delivery ZIP has changed or is missing. Start a new export.')
        for job in receipt['jobs']:
            target = (folder/job['relative_output']).resolve()
            if not target.is_relative_to(folder):raise ValueError('Campaign output must stay inside its delivery folder')
            if job.get('status') == 'completed' and (not target.is_file() or _sha(target) != job.get('output_sha256')):
                raise ValueError('A completed output has changed or is missing. Start a new export to preserve the original receipt.')
    else:
        jobs = plan_exports(profile, sources)
        folder = Path(output_dir).resolve()/('campaign-'+uuid.uuid4().hex[:12])
        folder.mkdir(parents=True, exist_ok=False)
        receipt_path = folder/'campaign-receipt.json'
        receipt = {'version':1,'created':datetime.now(timezone.utc).isoformat(),'profile':profile,
                   'package':bool(package),'status':'running','jobs':jobs}
        for job in jobs:job.update(status='pending',source_sha256=_sha(job['source']))
        _write(receipt_path, receipt)
    cancelled = False
    try:
        receipt['status'] = 'running';_write(receipt_path, receipt)
        for index, job in enumerate(receipt['jobs'], 1):
            if job['status'] == 'completed':continue
            check_cancel(cancel_check)
            if progress:progress(f"Export {index}/{len(receipt['jobs'])}: {Path(job['source']).name} → {job['preset']}")
            target = folder/job['relative_output']
            try:
                if _sha(job['source']) != job['source_sha256']:raise ValueError('Source changed since this campaign started. Start a new export.')
                job_profile = {**profile,'preset':job['preset'],'naming':target.stem.replace('{','{{').replace('}','}}'),'colors':[],'fonts':[],'logo':profile.get('logo','')}
                result = run_project(job_profile, [Path(job['source'])], target.parent, False, cancel_check, progress, include_brand=False)
                if not result.ok or not result.outputs:raise RuntimeError(str(result.details.get('failures', 'Export failed')))
                actual = result.outputs[0].resolve()
                if not actual.is_relative_to(folder):raise RuntimeError('Unexpected export destination')
                job.update(status='completed',relative_output=actual.relative_to(folder).as_posix(),output_sha256=_sha(actual),error='')
            except StudioCancelled:raise
            except Exception as exc:job.update(status='failed',error=str(exc))
            _write(receipt_path, receipt)
    except StudioCancelled:cancelled=True
    receipt['status'] = 'cancelled' if cancelled else 'completed' if all(j['status']=='completed' for j in receipt['jobs']) else 'partial'
    _write(receipt_path, receipt)
    outputs = [folder/j['relative_output'] for j in receipt['jobs'] if j['status']=='completed']
    from campaign_checks import check_delivery,save_check_report
    report_path=folder/'delivery-checks.json'
    check_report=None
    receipt.pop('check_error',None)
    receipt.pop('delivery_check',None)
    if not cancelled:
        try:
            check_report=check_delivery(receipt_path,cancel_check=cancel_check,progress=progress)
            save_check_report(check_report,report_path)
            receipt['delivery_check']={key:check_report[key] for key in ('status','errors','warnings','checked')}
            if check_report['errors']:receipt['check_error']='Delivery checks need attention. Open Check delivery for details.'
        except StudioCancelled:receipt['status']='cancelled'
        except Exception as exc:receipt['check_error']='Delivery checks could not finish: '+str(exc)
        _write(receipt_path,receipt)
    if receipt['status']=='completed' and not receipt.get('check_error') and package and not receipt.get('archive'):
        try:
            index_path=folder/'delivery-index.json'
            _write(index_path, {'client':profile.get('client',''),'project':profile['project'],
                               'files':[{'file':j['relative_output'],'preset':j['preset'],'sha256':j['output_sha256']} for j in receipt['jobs']]})
            # Package only the planned outputs, even if users added files to a
            # variant folder between an interrupted export and its resume.
            with tempfile.TemporaryDirectory(prefix='.shadow-package-',dir=folder) as td:
                package_root=Path(td)
                for path in outputs:
                    check_cancel(cancel_check)
                    destination=package_root/path.relative_to(folder)
                    destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,destination)
                staged_index=package_root/index_path.name;shutil.copy2(index_path,staged_index)
                variants=list(dict.fromkeys(package_root/path.parent.relative_to(folder) for path in outputs))
                archive = build_delivery_package([*variants,staged_index], folder/'campaign-delivery.zip', client=profile.get('client',''),project=profile['project'],cancel_check=cancel_check,progress=progress)
            receipt.pop('package_error',None)
            receipt['archive'] = archive.name;receipt['archive_sha256']=_sha(archive);outputs.append(archive);_write(receipt_path, receipt)
        except StudioCancelled:receipt['status']='cancelled';_write(receipt_path, receipt)
        except Exception as exc:receipt['package_error']=str(exc);_write(receipt_path, receipt)
    elif receipt.get('archive'):outputs.append(folder/receipt['archive'])
    if check_report is not None:outputs.append(report_path)
    outputs.append(receipt_path)
    failures = [j for j in receipt['jobs'] if j['status']!='completed']
    ok = receipt['status']=='completed' and not receipt.get('check_error') and (not package or bool(receipt.get('archive')))
    return StudioResult(outputs, {'receipt':str(receipt_path),'folder':str(folder),'exported':len(receipt['jobs'])-len(failures),
                                 'total':len(receipt['jobs']),'status':receipt['status'],'failures':failures,'package_error':receipt.get('package_error',''),
                                 'check_error':receipt.get('check_error',''),'delivery_check':receipt.get('delivery_check'), 'check_report':str(report_path) if check_report is not None else ''},ok)
