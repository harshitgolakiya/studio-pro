"""Local review campaigns: snapshot versions, attributed decisions and gated delivery."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
import uuid

from settings import get_app_data_dir
from studio_runtime import StagedOutput, check_cancel

STATUSES = ('Draft', 'Needs changes', 'Approved')


def _now():return datetime.now(timezone.utc).isoformat()


def _sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def reviews_dir():
    folder=get_app_data_dir()/'review-campaigns';folder.mkdir(parents=True,exist_ok=True);return folder


def _write(path,data):
    with StagedOutput(Path(path),overwrite=True) as stage:stage.path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')


@contextmanager
def _lock(path):
    """Serialize mutations across local app instances, without stale lock files."""
    with (Path(path).parent/'.review.lock').open('a+b') as stream:
        if stream.tell()==0:stream.write(b'0');stream.flush()
        deadline=time.monotonic()+10
        while True:
            try:
                stream.seek(0)
                if __import__('sys').platform=='win32':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>deadline:raise RuntimeError('This campaign is busy in another window. Try again.')
                time.sleep(.05)
        try:yield
        finally:
            stream.seek(0)
            if __import__('sys').platform=='win32':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)


def load_review(path):
    path=Path(path).resolve();data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('version')!=1 or not isinstance(data.get('assets'),list) or not data['assets']:raise ValueError('Invalid review campaign')
    for asset in data['assets']:
        if not asset.get('versions'):raise ValueError('Review asset has no versions')
        for version in asset['versions']:
            snapshot=(path.parent/version['path']).resolve()
            if not snapshot.is_relative_to(path.parent):raise ValueError('Review snapshot must stay inside its campaign')
            if version['status'] not in STATUSES:raise ValueError('Invalid review status')
    return data


def list_reviews():
    found=[]
    for path in reviews_dir().glob('*/review.json'):
        try:found.append((path,load_review(path)))
        except (OSError,ValueError,KeyError,TypeError):continue
    return sorted(found,key=lambda item:item[1]['created'],reverse=True)


def _snapshot(folder,source):
    source=Path(source).resolve()
    if not source.is_file():raise ValueError(f'Choose a file: {source.name}')
    digest=_sha(source);identifier=uuid.uuid4().hex
    target=folder/'versions'/identifier/source.name
    with StagedOutput(target) as stage:
        shutil.copy2(source,stage.path)
        if _sha(stage.path)!=digest or _sha(source)!=digest:raise ValueError('The source changed while copying. Try again.')
    return {'id':identifier,'name':source.name,'path':stage.output.relative_to(folder).as_posix(),
            'sha256':digest,'created':_now(),'status':'Draft','comments':[],'decisions':[]}


def create_review(name,sources,client='',directory=None,cancel_check=None):
    if not str(name).strip():raise ValueError('Enter a campaign name')
    sources=list(dict.fromkeys(Path(p).resolve() for p in sources))
    if not sources:raise ValueError('Choose files to review')
    folder=(Path(directory) if directory else reviews_dir())/uuid.uuid4().hex;folder.mkdir(parents=True)
    path=folder/'review.json'
    try:
        assets=[]
        for source in sources:
            check_cancel(cancel_check)
            asset_name=f'{source.parent.name} / {source.name}' if sum(p.name==source.name for p in sources)>1 else source.name
            assets.append({'id':uuid.uuid4().hex,'name':asset_name,'versions':[_snapshot(folder,source)]})
        _write(path,{'version':1,'id':folder.name,'name':str(name).strip(),'client':str(client).strip(),'created':_now(),'assets':assets})
    except BaseException:
        # Only the newly allocated, verified campaign folder belongs to us.
        assert folder.resolve().is_relative_to((Path(directory) if directory else reviews_dir()).resolve())
        shutil.rmtree(folder);raise
    return path


def review_export(receipt,directory=None,cancel_check=None):
    path=Path(receipt).resolve();data=json.loads(path.read_text(encoding='utf-8'));sources=[]
    if data.get('version')!=1 or not isinstance(data.get('jobs'),list):raise ValueError('Invalid campaign export receipt')
    for job in data['jobs']:
        if job.get('status')!='completed':continue
        source=(path.parent/job['relative_output']).resolve()
        if not source.is_relative_to(path.parent) or not source.is_file() or _sha(source)!=job.get('output_sha256'):raise ValueError('An exported file has changed or is missing. Re-export before reviewing it.')
        sources.append(source)
    profile=data['profile']
    return create_review(profile['project'],sources,profile.get('client',''),directory,cancel_check)


def find_version(data,asset_id,version_id=None):
    asset=next((a for a in data['assets'] if a['id']==asset_id),None)
    if not asset:raise ValueError('Select an asset')
    version=asset['versions'][-1] if version_id is None else next((v for v in asset['versions'] if v['id']==version_id),None)
    if not version:raise ValueError('Select a version')
    return asset,version


def version_status(path,version):
    snapshot=(Path(path).resolve().parent/version['path']).resolve()
    if not snapshot.is_relative_to(Path(path).resolve().parent):raise ValueError('Invalid review snapshot path')
    if not snapshot.is_file():return 'Missing'
    if _sha(snapshot)!=version['sha256']:return 'Changed'
    if version['status']=='Approved':
        decisions=version.get('decisions',[])
        if not decisions or decisions[-1].get('status')!='Approved' or decisions[-1].get('sha256')!=version['sha256']:return 'Changed'
    return version['status']


def add_revision(path,asset_id,source):
    path=Path(path).resolve()
    with _lock(path):
        data=load_review(path);asset,_=find_version(data,asset_id)
        asset['versions'].append(_snapshot(path.parent,source));_write(path,data)


def add_comment(path,asset_id,version_id,author,text,anchor=None):
    if not str(author).strip() or not str(text).strip():raise ValueError('Enter your name and a comment')
    if anchor is not None:
        import math
        if not isinstance(anchor,dict) or type(anchor.get('page')) is not int or anchor['page']<1 or any(type(anchor.get(key)) not in (int,float) or not math.isfinite(anchor[key]) or not 0<=anchor[key]<=1 for key in ('x','y')):raise ValueError('Invalid comment location')
        anchor={key:anchor[key] for key in ('page','x','y')}
    path=Path(path).resolve()
    with _lock(path):
        data=load_review(path);_,version=find_version(data,asset_id,version_id)
        comment={'author':str(author).strip(),'text':str(text).strip(),'created':_now()}
        if anchor is not None:comment['anchor']=anchor
        version['comments'].append(comment);_write(path,data)


def decide(path,asset_id,version_id,author,status):
    if not str(author).strip():raise ValueError('Enter your reviewer name')
    if status not in STATUSES:raise ValueError('Choose a review status')
    path=Path(path).resolve()
    with _lock(path):
        data=load_review(path);asset,version=find_version(data,asset_id,version_id)
        if asset['versions'][-1]['id']!=version_id:raise ValueError('Only the current version can change status')
        if version_status(path,version) in {'Missing','Changed'}:raise ValueError('This snapshot has changed or is missing. Add a new revision before approving.')
        version['status']=status;version['decisions'].append({'author':str(author).strip(),'status':status,'created':_now(),'sha256':version['sha256']});_write(path,data)


def package_approved(path,destination,cancel_check=None,progress=None):
    from archive_tools import build_delivery_package
    path=Path(path).resolve()
    with _lock(path):
        data=load_review(path);approved=[(a,a['versions'][-1]) for a in data['assets'] if version_status(path,a['versions'][-1])=='Approved']
        if not approved:raise ValueError('No current versions are approved. Review and approve at least one file first.')
        with tempfile.TemporaryDirectory(prefix='shadow-approved-') as td:
            folder=Path(td);files=[];index=[]
            for asset,version in approved:
                check_cancel(cancel_check)
                target=folder/(asset['id'][:8]+'-'+version['name']);shutil.copy2(path.parent/version['path'],target)
                if _sha(target)!=version['sha256']:raise ValueError('An approved file changed during packaging. Review it again.')
                files.append(target);decision=version['decisions'][-1]
                index.append({'file':target.name,'version':version['id'],'sha256':version['sha256'],'approved_by':decision['author'],'approved_at':decision['created']})
            public=folder/'approved-files.json';public.write_text(json.dumps({'campaign':data['name'],'client':data['client'],'files':index,'excluded':len(data['assets'])-len(approved)},indent=2),encoding='utf-8');files.append(public)
            return build_delivery_package(files,Path(destination),client=data['client'],project=data['name'],cancel_check=cancel_check,progress=progress)
