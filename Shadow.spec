# -*- mode: python ; coding: utf-8 -*-
#
# Built as a folder (onedir), not a single-file exe: the bundled FFmpeg
# binaries add ~200MB, and onefile mode re-extracts everything to a temp
# directory on every launch -- painful at this size. Onedir keeps
# ffmpeg.exe/ffprobe.exe sitting in bin\ next to Shadow.exe so startup is
# instant. The Inno Setup installer (installer.iss) packages the whole
# dist\Shadow\ folder.
#
# assets/ is globbed rather than listed file-by-file: a prior release
# listed only icon.ico and silently dropped assets/theme.json (the CTk
# color theme main.py loads at startup), which crashed the packaged exe on
# every launch. Globbing means a new file dropped into assets/ is bundled
# automatically instead of needing this spec edited too.
import glob
import os

from PyInstaller.utils.hooks import collect_submodules

# reportlab.graphics.barcode (pulled in by xhtml2pdf for Markdown -> PDF)
# resolves its barcode implementations by name at runtime rather than a
# static import PyInstaller's analyzer can see, so the packaged exe crashed
# with "No module named 'reportlab.graphics.barcode.code128'" on first PDF
# export -- collect_submodules walks the actual package on disk instead of
# relying on import statements.
reportlab_barcode_modules = collect_submodules('reportlab.graphics.barcode')

asset_datas = [
    (path, 'assets')
    for path in glob.glob(os.path.join('assets', '*'))
    if os.path.isfile(path)
]

# Bundled Inter (body) / Outfit (display) fonts -- see font_loader.py, which
# registers these as process-private GDI fonts at startup so the app never
# depends on what happens to be installed on the customer's machine.
font_datas = [
    (path, 'assets/fonts')
    for path in glob.glob(os.path.join('assets', 'fonts', '*'))
    if os.path.isfile(path)
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        ('vendor/ffmpeg/ffmpeg.exe', 'bin'),
        ('vendor/ffmpeg/ffprobe.exe', 'bin'),
    ],
    datas=[
        *asset_datas,
        *font_datas,
        ('vendor/ffmpeg/LICENSE-ffmpeg-GPLv3.txt', 'bin'),
    ],
    hiddenimports=[
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL.ExifTags',
        'PIL.ImageSequence',
        'PIL.AvifImagePlugin',
        'customtkinter',
        'drag_drop',
        'converter',
        'licensing',
        'settings',
        'watermark',
        'media_engine',
        'preview_modal',
        'license_dialog',
        'url_downloader',
        'url_downloader_dialog',
        'video_trimmer_dialog',
        'watch_folder',
        'watch_folder_dialog',
        'yt_dlp',
        'utils',
        'cryptography',
        'cryptography.hazmat.primitives.asymmetric.ed25519',
        'doc_converter',
        'docx',
        'mammoth',
        'markdownify',
        'markdown',
        'pypdf',
        'xhtml2pdf',
        'reportlab',
        *reportlab_barcode_modules,
        'font_loader',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Shadow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Shadow',
)
