"""Consistent social crop geometry and full-resolution PNG preparation."""
import hashlib
import json
from pathlib import Path
import tempfile
from PIL import Image,ImageOps

SOCIAL_SIZES={'Social square':(1080,1080),'Social portrait':(1080,1350),'Social story':(1080,1920)}


def crop_box(size,target,position=(.5,.5)):
    width,height=size;ratio=target[0]/target[1]
    cw,ch=(height*ratio,height) if width/height>ratio else (width,width/ratio)
    left,top=(width-cw)*position[0],(height-ch)*position[1]
    return left,top,left+cw,top+ch


def source_sha(source):
    with Path(source).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def social_rgb(image):
    if 'A' in image.getbands() or (image.mode=='P' and 'transparency' in image.info):
        rgba=image.convert('RGBA');background=Image.new('RGB',image.size,'white');background.paste(rgba,mask=rgba.getchannel('A'));return background
    return image.convert('RGB')


def social_settings(profile,preset):
    from agency_projects import PRESETS
    from recipes import coerce_settings
    settings=coerce_settings({**profile.get('settings',{}),**PRESETS[preset]})
    settings.update(target_format='PNG',lossless=True,enable_resize=False,aspect_ratio='Original',replace_source=False,overwrite=False)
    if profile.get('watermark'):
        logo=profile.get('logo','')
        if not logo or not Path(logo).is_file():raise ValueError('Choose a valid brand logo')
        settings.update(enable_watermark=True,watermark_logo_path=logo)
    return settings


def settings_sha(profile,preset):
    settings=social_settings(profile,preset)
    logo=settings.get('watermark_logo_path')
    if settings.get('enable_watermark') and logo:
        settings['watermark_logo_sha256']=source_sha(logo)
    return hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()


def crop_position(profile,source,preset):
    position=profile.get('crop_positions',{}).get(str(Path(source).resolve()),{}).get(preset)
    if not position:return (.5,.5)
    if source_sha(source)!=position['source_sha256'] or settings_sha(profile,preset)!=position['settings_sha256']:
        raise ValueError('The source or image settings changed after framing. Adjust crops again and start a new export.')
    return position['x'],position['y']


def prepare_crop_preview(profile,source):
    from headless_cli import convert_path
    before=source_sha(source)
    with tempfile.TemporaryDirectory(prefix='shadow-crop-preview-') as td:
        result=convert_path(Path(source),Path(td),social_settings(profile,'Social square'))
        if result.status!='Completed':raise ValueError(result.error)
        with Image.open(result.output_path) as image:
            prepared=social_rgb(image);prepared.thumbnail((1600,1600))
    if source_sha(source)!=before:raise ValueError('The source changed while preparing its preview')
    return prepared,before
