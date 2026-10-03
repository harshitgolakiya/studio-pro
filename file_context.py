"""File capabilities and the discoverable tool catalog used by the workspace."""
from dataclasses import dataclass
from pathlib import Path

from converter import SUPPORTED_EXTENSIONS
from media_engine import SUPPORTED_AUDIO_EXTENSIONS, SUPPORTED_VIDEO_EXTENSIONS
from doc_converter import SUPPORTED_DOCUMENT_EXTENSIONS
from data_tools import DATA_READ_EXTENSIONS
from archive_tools import ARCHIVE_EXTENSIONS
from studio_actions import ACTION_LABELS
from studio_workflows import WORKFLOWS

EXTRA_EXTENSIONS = DATA_READ_EXTENSIONS | ARCHIVE_EXTENSIONS | {'.srt', '.vtt', '.eps', '.ai', '.indd', '.ttf', '.otf'}
IMPORT_EXTENSIONS = SUPPORTED_EXTENSIONS | SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS | SUPPORTED_DOCUMENT_EXTENSIONS | EXTRA_EXTENSIONS


def file_tags(path: Path) -> set[str]:
    if path.is_dir():
        return {'folder'}
    ext = path.suffix.lower()
    tags = {'file'}
    for extensions, tag in ((SUPPORTED_EXTENSIONS, 'image'), (SUPPORTED_AUDIO_EXTENSIONS, 'audio'),
                            (SUPPORTED_VIDEO_EXTENSIONS, 'video'), (SUPPORTED_DOCUMENT_EXTENSIONS, 'document'),
                            (DATA_READ_EXTENSIONS, 'data'), (ARCHIVE_EXTENSIONS, 'archive')):
        if ext in extensions:
            tags.add(tag)
    if ext == '.pdf': tags.add('pdf')
    if ext in {'.docx', '.pptx', '.xlsx'}: tags.add('office')
    if ext in {'.xlsx', '.xlsm'}: tags.add('workbook')
    if ext in {'.srt', '.vtt'}: tags.add('subtitle')
    if ext in {'.txt', '.md', '.markdown'}: tags.add('text')
    if ext in {'.eps', '.ai', '.indd'}: tags.add('design')
    if ext in {'.ttf', '.otf'}: tags.add('font')
    if 'image' in tags and ext in {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp', '.gif'}:
        tags.add('ocr-image')
    return tags


@dataclass(frozen=True)
class Tool:
    key: str
    title: str
    group: str
    description: str
    tags: frozenset[str]
    multiple: bool = False
    no_input: bool = False

    def inputs(self, paths):
        return [p for p in paths if self.tags.intersection(file_tags(p))]


def tool_catalog() -> list[Tool]:
    def tool(key, title, group, description, tags='', multiple=False, no_input=False):
        return Tool(key, title, group, description, frozenset(tags.split()), multiple, no_input)
    tools = [
        tool('convert-image', 'Convert & edit images', 'Convert', 'Change format, resize, rename, watermark, or reduce image size.', 'image', True),
        tool('convert-video', 'Convert & compress video', 'Convert', 'Change video format, resolution, or file size.', 'video', True),
        tool('convert-audio', 'Convert audio format', 'Convert', 'Export MP3, AAC, Opus, or WAV audio.', 'audio', True),
        tool('convert-document', 'Convert documents', 'Convert', 'Export PDF or another compatible document format.', 'document', True),
        tool('preview', 'Preview file', 'Inspect', 'Inspect the selected file before processing it.', 'image video audio document'),
        tool('optimize', 'Compare image quality', 'Images', 'Compare codecs, file size, and image quality.', 'image'),
        tool('trim', 'Trim video', 'Video', 'Choose the start and end of a clip.', 'video'),
        tool('transcribe', 'Audio to text', 'Speech', 'Turn a recording or video into text or subtitles.', 'audio video'),
        tool('speak', 'Text to audio', 'Speech', 'Write a script or load document text and create a voiceover.', 'text document', False, True),
        tool('audio', 'Clean & convert audio', 'Audio', 'Normalize loudness, reduce noise, trim, and export audio.', 'audio video'),
        *[tool(key, title, 'PDF', description, 'pdf', key == 'pdf-merge') for key, title, description in (
            ('pdf-merge', 'Merge PDFs', 'Combine selected PDFs in queue order.'),
            ('pdf-extract', 'Extract PDF pages', 'Keep a page range or selected pages.'),
            ('pdf-rotate', 'Rotate PDF pages', 'Correct page orientation.'),
            ('pdf-compress', 'Compress PDF', 'Reduce PDF size without resampling images.'),
            ('pdf-images', 'PDF pages to images', 'Export page images in a ZIP.'))],
    ]
    base = {
        'ocr': ('OCR', 'Read text from a scan or make a searchable PDF.', 'pdf ocr-image', False),
        'data-convert': ('Data', 'Export structured data to another format.', 'data', False),
        'data-clean': ('Data', 'Remove duplicate rows and normalize column names.', 'data', False),
        'data-export-sheets': ('Data', 'Export each workbook sheet separately.', 'workbook', False),
        'archive-create': ('Archives', 'Pack the selected files or folders.', 'file folder', True),
        'archive-extract': ('Archives', 'Extract an archive into an output folder.', 'archive', False),
        'delivery-create': ('Delivery', 'Package deliverables with checksums.', 'file folder', True),
        'delivery-verify': ('Delivery', 'Check the files and checksums inside a package.', 'archive', False),
    }
    for key, (group, description, tags, multiple) in base.items():
        tools.append(tool(key, ACTION_LABELS[key], group, description, tags, multiple))
    tags_by_group = {'PDF': 'pdf', 'Office': 'office', 'Data': 'data', 'Subtitles': 'subtitle',
                     'Speech': 'audio video', 'Delivery': 'archive', 'Print': 'pdf',
                     'Projects': 'file folder', 'Integrations': 'file'}
    overrides = {'text-translate': 'text', 'folder-manifest': 'folder', 'folder-verify': 'folder',
                 'print-import': 'design', 'print-fonts': 'pdf font', 'print-cmyk': 'pdf image',
                 'plugin-codec': 'image', 'plugin-process': 'image'}
    for key, (group, label, _) in WORKFLOWS.items():
        tools.append(tool(key, label, group, f'{label} with local processing and saved output.',
                          overrides.get(key, tags_by_group[group]), key in {'speech-batch', 'project-delivery'}, key == 'pdf-identity'))
    for key, title, group, description in (
        ('projects', 'Projects & brand kits', 'Projects', 'Save client presets, naming rules, and delivery settings.'),
        ('integrations', 'Publishing & automation', 'Integrations', 'Manage publishing adapters, plugins, hooks, and the local API.'),
        ('models', 'Voices & language models', 'Setup', 'Install or manage local speech, OCR, and translation models.'),
        ('engines', 'Engine readiness', 'Setup', 'Check the local engines and models.'),
        ('history', 'History', 'Workspace', 'Review earlier conversions.'),
        ('recipes', 'Saved recipes', 'Workspace', 'Save or reuse conversion settings.'),
        ('watch', 'Watch a folder', 'Automation', 'Process files arriving in a chosen folder.'),
        ('download', 'Download media', 'Automation', 'Import media from a URL.'),
        ('license', 'License', 'Setup', 'Manage your license.'),
        ('about', 'About Shadow', 'Setup', 'Version, credits, and application information.')):
        tools.append(tool(key, title, group, description, no_input=True))
    return tools
