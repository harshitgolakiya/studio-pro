"""Role shortcuts reuse real tools; the full catalog remains available to every team."""
ROLE_TOOLS = {
    'All teams': ('speak','transcribe','pdf-merge','convert-image','convert-video','archive-extract'),
    'Design & production': ('convert-image','optimize','print-cmyk','print-preflight','print-fonts','project-delivery'),
    'Video & social': ('convert-video','trim','speak','transcribe','subtitle-edit','audio'),
    'Content & accounts': ('preview','convert-document','pdf-merge','ocr','projects','project-delivery'),
    'Operations': ('data-clean','data-convert','data-export-sheets','pdf-fill','folder-manifest','delivery-verify'),
    'Developers & IT': ('data-schema','data-validate','archive-create','archive-inspect','folder-verify','watch'),
}
