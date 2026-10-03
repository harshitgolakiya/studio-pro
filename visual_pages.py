"""Read-only raster/page previews shared by visual reviews and comparisons."""
from pathlib import Path
from PIL import Image,ImageOps
from document_cache import preview_pdf
from office_engine import OFFICE_EXTENSIONS
from pdf_tools import render_pdf_page


def load_visual(source,cancel_check=None):
    source=Path(source)
    if source.suffix.lower()=='.pdf':payload=source
    elif source.suffix.lower() in OFFICE_EXTENSIONS:payload,_=preview_pdf(source,cancel_check)
    else:
        with Image.open(source) as image:
            raster=ImageOps.exif_transpose(image).convert('RGB');raster.thumbnail((2400,2400))
        return {'kind':'image','payload':raster,'count':1,'first':raster}
    image,count=render_pdf_page(payload)
    return {'kind':'pages','payload':payload,'count':count,'first':image}


def visual_page(document,page):
    if page>=document['count']:return None
    if page==0:return document['first']
    return render_pdf_page(document['payload'],page)[0]


def fitted_rect(size,width,height,padding=16):
    scale=min(max(1,width-padding*2)/size[0],max(1,height-padding*2)/size[1])
    w,h=size[0]*scale,size[1]*scale
    return ((width-w)/2,(height-h)/2,w,h)


def normalized_point(rect,x,y):
    left,top,width,height=rect
    if not(left<=x<=left+width and top<=y<=top+height):return None
    return ((x-left)/width,(y-top)/height)
