# -*- mode: python ; coding: utf-8 -*-
#
# macOS counterpart to Shadow.spec. Built as onedir + BUNDLE() to produce a
# proper Shadow.app (Shadow.spec's Windows-only EXE/COLLECT pair can't
# produce a .app bundle on its own). Must be run ON macOS -- PyInstaller
# does not cross-compile from Windows to macOS. The bundled FFmpeg binaries
# are expected at vendor/ffmpeg-mac/{ffmpeg,ffprobe} (no .exe suffix); the
# CI workflow (.github/workflows/build-macos.yml) populates that folder via
# Homebrew before invoking this spec.
#
# UPX is skipped here (unlike Shadow.spec): compressing Mach-O binaries with
# UPX is a common source of Gatekeeper/codesign breakage and isn't reliably
# available on macOS runners.
import glob
import os

from PyInstaller.utils.hooks import collect_submodules

reportlab_barcode_modules = collect_submodules('reportlab.graphics.barcode')

asset_datas = [
    (path, 'assets')
    for path in glob.glob(os.path.join('assets', '*'))
    if os.path.isfile(path)
]

font_datas = [
    (path, 'assets/fonts')
    for path in glob.glob(os.path.join('assets', 'fonts', '*'))
    if os.path.isfile(path)
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        ('vendor/ffmpeg-mac/ffmpeg', 'bin'),
        ('vendor/ffmpeg-mac/ffprobe', 'bin'),
    ],
    datas=[
        *asset_datas,
        *font_datas,
    ],
    hiddenimports=[
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL.ExifTags',
        'PIL.ImageSequence',
        'PIL.AvifImagePlugin',
        'pillow_heif',
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
        'format_browser',
        'recipes',
        'recipe_dialog',
        'queue_store',
        'optimizer',
        'optimizer_dialog',
        'command_palette',
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
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.icns',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Shadow',
)

app = BUNDLE(
    coll,
    name='Shadow.app',
    icon='assets/icon.icns',
    bundle_identifier='com.shadowmediastudio.shadow',
    info_plist={
        'CFBundleName': 'Shadow',
        'CFBundleDisplayName': 'Shadow Media Studio Pro',
        'CFBundleShortVersionString': '2.0.0',
        'CFBundleVersion': '2.0.0',
        'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': 'Shadow Media Studio',
    },
)
