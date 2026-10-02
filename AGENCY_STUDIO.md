# Shadow Agency Studio

The app now combines its image/video studio with Office documents, PDF tools,
English speech recognition, neural voice generation, and audio preparation.
Open **Studio Tools** in the header or command palette to access the new tools.

## Available workflows

| Team / workflow | Inputs | Outputs / actions |
| --- | --- | --- |
| Accounts and proposals | DOC, DOCX, DOCM, ODT, OTT, RTF, WPS, FODT | PDF, DOC, DOCX, ODT, RTF; extracted Markdown, TXT, HTML |
| Strategy and presentations | PPT, PPTX, PPTM, PPS, PPSX, ODP, OTP, FODP | PDF, PPT, PPTX, ODP; extracted slide text |
| Finance and reporting | XLS, XLSX, XLSM, ODS, OTS, CSV, TSV, FODS | PDF, XLS, XLSX, ODS, CSV, TSV; extracted sheet contents |
| Document delivery | PDF | Merge, extract ranges, rotate, lossless stream compression, page PNGs in ZIP |
| Document inspection | Office / PDF / Markdown / HTML / TXT | Native page preview and extracted text; open in default app |
| Interviews and meetings | Audio recordings and video soundtracks | English TXT, SRT, VTT, timestamped JSON transcripts |
| Voiceovers and scripts | Typed text or extracted document text | Local neural speech in WAV; adjustable speaking speed |
| Audio delivery | Audio / video | WAV, MP3, FLAC, AAC/M4A, Opus; trim, loudness normalization, steady-noise reduction |
| Design and production | Existing supported image/video formats | Existing compression, conversion, RAW/SVG/PSD workflows, recipes, previews, and batch processing |

The file picker also recognizes professional media containers such as MXF,
MTS/M2TS, MPEG, FLV, AIFF, CAF, and AC3. Their actual codecs must be readable
by the bundled FFmpeg build.

## Source setup (Windows)

Use the project's existing Python environment:

```powershell
cd C:\projects\webp\webp-compressor
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_studio.ps1 -Python '..\.venv\Scripts\python.exe'
..\.venv\Scripts\python.exe main.py
```

The setup downloads a checksum-verified LibreOffice Windows x64 MSI and extracts
it into `vendor/libreoffice` without installing it system-wide. It also downloads
the English faster-whisper `base.en` model and the Piper Lessac medium voice into
`vendor/models`. Setup needs internet access; file processing uses local engines
and does not download models or upload media.

`-SkipOffice` and `-SkipModels` let you reuse existing engines. To use an installed
LibreOffice, set `SHADOW_LIBREOFFICE` to `soffice.com`/`soffice.exe`. Set
`SHADOW_MODEL_DIR` to a different local model directory if needed. Custom local
Whisper directories and Piper `.onnx` voices can also be chosen in Studio Tools.
Keep a Piper voice's matching `.onnx.json` file beside the model.

## Batch use

Add documents with the normal file picker, drag and drop, or Studio Tools.
The target menu adapts to the selected document family. Selecting a presentation
shows presentation outputs; selecting a spreadsheet shows spreadsheet outputs.
Each conversion runs in the existing background batch queue. An individual
failure does not stop other files. Output publication is atomic, originals are
kept by default, and name collisions receive numbered filenames.

For mixed document families, choose PDF or apply per-file recipe overrides.

```powershell
..\.venv\Scripts\python.exe -m headless_cli .\proposal.doc --output .\out --format PDF --json
..\.venv\Scripts\python.exe -m headless_cli .\pitch.pptx --output .\out --format PDF --json
..\.venv\Scripts\python.exe -m headless_cli .\meeting.mp4 --output .\out --format 'Transcript: SRT' --json
..\.venv\Scripts\python.exe -m headless_cli .\script.txt --output .\out --format 'Speech: WAV' --json
```

`--speech-model`, `--voice`, and `--language` select local speech assets. The bundled
model is English-only. Auto language detection requires a multilingual model.

## Full Windows package

Install `requirements-studio.txt` and run setup before building. Both PyInstaller
specs collect installed speech/PDF dependencies and staged engine/model files.
The Windows installer includes the whole application directory.

```powershell
..\.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist-studio --workpath build-studio Shadow.spec
.\dist-studio\Shadow\Shadow.exe --studio-smoke-report .\studio-verification\packaged-smoke.json
```

The smoke command creates a JSON report and exits nonzero if a bundled engine
fails. It tests actual Office exports, PDF rendering, speech synthesis followed by
transcription, and audio processing. It does not download missing dependencies.

The package is a folder build. Keep `Shadow.exe` and `_internal` together; copying
only the EXE does not include the engines. The full runtime can exceed 1 GB.

To compile an installer from this separate build directory:

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DMyAppSource=dist-studio\Shadow /DMyAppOutputName=Shadow-Agency-Studio-Setup /Ostudio-verification\installer installer.iss
```

macOS needs native LibreOffice and a build performed on macOS; Windows validation
does not establish macOS runtime compatibility.

## Fidelity and supported boundaries

- Office → PDF uses LibreOffice's native exporters rather than extracting text.
  Font substitution, unsupported Office features, embedded objects, animations,
  and complex layout differences can still affect fidelity. Inspect Pages before delivery.
- PDF → DOCX is text reflow. It does not reconstruct the original Word document.
- Scanned PDFs need OCR; OCR is not included in this expansion.
- CSV/TSV export includes the active spreadsheet sheet, not every sheet.
- Password-protected, DRM-restricted, corrupt, and unsupported files return errors.
- Transcripts need human review. Speaker diarization and translation are not included.
- Audio denoising reduces steady noise; it is not a voice isolation engine.
- Layout or editable conversion between unrelated families (e.g. PPT → XLSX) is
  not a meaningful route and is rejected.

## Further agency / IT expansion

These are future work, not implemented features:

- [ ] OCR for scans/screenshots, searchable PDFs, and multilingual text extraction.
- [ ] PDF password handling, redaction, forms, signatures, repair, and structured table extraction.
- [ ] Higher-fidelity PDF → Office reconstruction and native document editing.
- [ ] Spreadsheet data tooling: CSV/JSON/XML/YAML, schema validation, multi-sheet export, cleanup.
- [ ] Safe ZIP/7z/TAR archive workflows, manifests, checksums, and client delivery packages.
- [ ] Subtitle editing, translation, speaker labels, voice isolation, and speech batch queues.
- [ ] Multilingual speech models and a voice/model management interface.
- [ ] Print and design tools: EPS/AI/INDD import adapters, font inspection, PDF preflight, CMYK delivery.
- [ ] Client projects, brand kits, social/export presets, naming templates, and reusable delivery workflows.
- [ ] Integration of the existing plugin SDK, hooks, API, and publishing adapters into the app UI.
- [ ] Full packaged regression matrix across Windows and both macOS architectures.

## Engine references and bundled notices

The integration uses the documented [LibreOffice command-line parameters](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), and
[Piper](https://github.com/OHF-Voice/piper1-gpl). LibreOffice's license/notice files
and the voice model card are kept with their staged resources. Third-party
components and model assets retain their own licenses.
