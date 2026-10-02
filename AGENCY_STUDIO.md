# Shadow Agency Studio

Agency Studio combines the original image/video converter with Office, PDF,
OCR, data, speech, print, project delivery, and integration workflows.
Open **Studio Tools > More Tools** for the expanded controls.

## Implementation status

- [x] Integrate the expansion engines into Studio Tools and the headless CLI.
- [x] Print/design import adapters, font inspection, PDF preflight, and CMYK delivery.
- [x] Client projects, brand kits, export presets, naming, and reusable deliveries.
- [x] Plugin SDK, hooks, loopback API, and publishing controls.
- [ ] Final installer verification and macOS Apple Silicon/Intel regression matrix.

The shared dispatcher exposes **40 actions**. The original conversion queue,
Office/PDF tools, voice generation, and media conversion remain available.

## Workflows

| Area | Available operations |
| --- | --- |
| Office | Native DOC/DOCX/ODT, PPT/PPTX/ODP, XLS/XLSX/ODS conversions through bundled LibreOffice; PDF export; find/replace; document properties; open in the editor |
| PDF | Page operations, rendering, positioned editable export, tables, passwords, flattened redaction, form inspection/fill, identity creation, signing/verification, repair |
| OCR | Images and scanned PDFs to text or searchable PDF; page ranges, DPI, language scripts, force recognition |
| Data | CSV/TSV/JSON/JSONL/XML/YAML/XLSX, cleanup, schemas, validation, all-sheet export |
| Archives | ZIP/7z/TAR creation, encrypted 7z, safe extraction, inspection |
| Delivery | Packages with manifests/checksums, verification, folder manifests and integrity checks |
| Speech | English/multilingual transcription, subtitles, speaker labels, speech-to-English, batch transcription, neural voices |
| Audio/subtitles | Media exports, loudness/steady-noise processing, speech isolation, subtitle edits and offline translation |
| Print | EPS/PS/AI import, conditional INDD adapter, font inspection, image-DPI/font preflight, ICC-based CMYK PDF/TIFF |
| Projects | Saved client profiles, brand colors/fonts/logo, naming templates, reusable export presets, delivery ZIP and brand-kit metadata |
| Integrations | Plugin discovery/exporters/hooks, local website assets, cloud storage, WordPress, design assets, loopback HTTP API |

The More Tools category menu includes OCR, Data, Archives & Delivery,
Advanced workflows, Models, Projects & Brand kits, and Integrations & API.
Advanced workflows expose typed options, password fields, file/folder browsing,
and JSON mappings where needed. Results show output paths and detailed reports.

## Runtime assets

The complete Windows build stages LibreOffice, FFmpeg, Ghostscript, and **53
catalog model entries**: English and multilingual base transcription, 13 voices,
additional OCR scripts, 25 translation pairs, speaker models, isolation, and CMYK
profile assets. Larger Whisper small/medium/large-v3 models remain optional in
Models. Installed assets run locally; selecting Install explicitly downloads a
model. Model cards, provenance, and upstream notices are retained.

## Source setup on Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-studio.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_studio.ps1 -Python '.\.venv\Scripts\python.exe'
.\.venv\Scripts\python.exe setup_full_models.py
.\.venv\Scripts\python.exe setup_model_notices.py
.\.venv\Scripts\python.exe main.py
```

Print runtime setup uses 7-Zip to unpack the verified Ghostscript distribution.
The Windows setup supports a verified LibreOffice mirror if the primary download
fails. Assets can live on another drive through directory junctions.

## CLI and automation

```powershell
.\.venv\Scripts\python.exe -m headless_cli .\scan.pdf --studio-action ocr --output .\out --format PDF --pages '1-3' --json
.\.venv\Scripts\python.exe -m headless_cli .\leads.csv --studio-action data-clean --output .\out --format JSON --drop-duplicates --normalize-headers --json
.\.venv\Scripts\python.exe -m headless_cli .\budget.xlsx --studio-action data-export-sheets --output .\out --format CSV --json
.\.venv\Scripts\python.exe -m headless_cli .\deliverables --studio-action delivery-create --output .\out --format ZIP --client Acme --project Launch --json
.\.venv\Scripts\python.exe -m headless_cli .\out\deliverables-delivery.zip --studio-action delivery-verify --output .\out --json
.\.venv\Scripts\python.exe -m headless_cli .\proposal.pdf --studio-action pdf-protect --output .\out --options .\password-options.json --json
.\.venv\Scripts\python.exe -m headless_cli --models list --json
```

`--options` reads a JSON object for the selected action; UI fields use the same
option definitions. `--models install --model-key KEY` and `--models remove
--model-key KEY` manage catalog assets. Archive password options enable encrypted
7z. Verification failures return nonzero. Originals are preserved and generated
files use collision-safe names.

The packaged executable accepts `--cli` followed by the same arguments.
`--cli-report PATH` captures JSON/text output for the windowed Windows app.
Integrations & API starts/stops a server restricted to loopback. It exposes
`GET /studio/actions` and `POST /studio/run`, alongside the original API routes.
Conversion hooks also run in packaged builds when explicitly enabled.

## Projects and publishing

Project profiles keep client/project, brand colors, font, optional logo, preset,
and a validated naming template. Social presets produce 1080x1080, 1080x1350,
or 1080x1920 images. Other presets cover web, print, documents, audio, and video.
Successful deliveries contain converted assets, brand-kit metadata when supplied,
and a checksum-backed ZIP. Failed batches report individual errors.

Publishing runs only when the user selects Publish. Provider configuration is
entered in the integration controls; saved project/brand metadata excludes private
absolute paths. Local website delivery confines assets to the chosen project root.

## Verification and packaging

```powershell
$env:SHADOW_TEST_FULL_STUDIO='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_agency_release.ps1 -WorkRoot 'D:\Shadow-Agency-Studio-Build\release'
```

The release script builds the executable, requires all 11 packaged engine checks
to pass, compiles the Inno Setup installer, and writes a SHA256 and JSON receipt.
Checks exercise real Office export, PDF rendering and signing, speech, audio, OCR,
translation, structured data, encrypted archives, print, and project delivery.
CI workflows perform source and packaged checks for Windows and both macOS
architectures before uploading installers. Reports establish readiness for each
specific artifact; source tests alone do not establish packaged readiness.

Current verification reports are under `studio-verification` and the release
work root's `verification` directory. The final platform status will be updated
after the installer and CI runs complete.

## Practical boundaries

- Office fidelity depends on fonts and supported document features. Inspect
  rendered pages before client delivery. PDF editable export uses positioned
  content and cannot recover original authoring structure perfectly.
- OCR, transcripts, translations, and speaker labels need human review.
- Redaction flattens affected pages; regions use page/left/top/right/bottom
  coordinates. Self-signed signatures can be valid while untrusted by readers.
- CSV/TSV queue export uses the active sheet. The all-sheet workflow exports each
  sheet separately. Data cleanup preserves cell strings.
- Print preflight checks font embedding and image DPI. It does not certify PDF/X,
  bleed, trapping, separations, or a printer's production specification. Choose
  the printer's ICC profile when required; the bundled profile is generic.
- INDD export requires installed Adobe InDesign on Windows or a matching PDF
  sidecar. The installer cannot include Adobe's proprietary application.
- Third-party runtime/model assets retain their own license terms. See
  THIRD_PARTY_NOTICES.md and the bundled model notices.
