# Shadow Agency Studio

Agency Studio combines the original image/video converter with Office, PDF,
OCR, data, speech, print, project delivery, and integration workflows.
Open **Explore tools** for the full catalog and role-based shortcuts.
See [AGENCY_RELEASE_PLAN.md](AGENCY_RELEASE_PLAN.md) for the agency workflow
audit, remaining release gates, and the free/offline service policy.

## Implementation status

- [x] Integrate the expansion engines into Studio Tools and the headless CLI.
- [x] Print/design import adapters, font inspection, PDF preflight, and CMYK delivery.
- [x] Client projects, brand kits, export presets, naming, and reusable deliveries.
- [x] Plugin SDK, hooks, loopback API, and publishing controls.
- [x] Windows full-model installer and clean installed runtime verification.
- [x] Packaged macOS Apple Silicon/Intel regression matrix.

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

The current Windows desktop stages LibreOffice, FFmpeg, Ghostscript, and **40
installed catalog entries**: English and multilingual base transcription, one
natural voice pack with four US/UK female/male choices,
additional OCR scripts, 25 translation pairs, speaker models, isolation, and CMYK
profile assets. The catalog contains 44 entries; larger transcription models remain optional in
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

Verification reports are under `studio-verification` and the release work root's
`verification` directory. Full Windows installer parts, checksums, and the
distribution ZIP are under `D:\Shadow-Agency-Studio-Build\release`; Mac DMGs are
in its `macos` directory.

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

Large full-model Windows releases use an installer executable with adjacent .bin
parts to avoid executable size limits. Keep every installer part together.
The release receipt includes a SHA256 for each part.

### Verification recorded on 2026-10-03

The full Windows source suite passed 439 tests in 375.812 seconds, with two skips
for the absent seller-only key generator. Five GPU tests subsequently passed,
including the additional macOS VideoToolbox case. All 11 packaged and clean
installed runtime checks passed. The installed CLI confirms 53 of 56 catalog
entries are present; the three larger Whisper models are optional.
The packaged UI exposes all 40 actions; local publishing, loopback API conversion,
and packaged Python hooks passed. The screen-scaling correction passed the six
focused UI/dispatcher tests and was checked in the final executable.

The macOS setup now uses setup_studio_macos.sh: pinned LibreOffice downloads
from a reachable mirror, SHA256 checks, and verification of the app signature.
The corrected Windows installer installed successfully to
`D:\Shadow-Agency-Studio`; a Shadow Agency Studio desktop shortcut opens it.
Installed local publishing, API conversion, Python hooks, and eight repeated
voice-isolation runs passed. The isolation fix also passed 30 source runs with
identical output hashes. Windows CI completed successfully:
https://github.com/harshitgolakiya/studio-pro/actions/runs/37065925499

The Windows installer was rebuilt with the frozen-worker startup correction and
installed into a fresh application directory. All 11 installed engine checks,
53 installed catalog entries, local publishing, API conversion, Python hooks,
eight deterministic isolation runs, and a spawned multiprocessing worker passed.
The desktop shortcut opens `D:\Shadow-Agency-Studio\Shadow.exe`.

Both macOS architectures passed the 440-test source suite and all 11 source and
packaged engine checks. Frozen multiprocessing initialization now runs before
application imports, so helper processes perform their own work and the packaged
app exits cleanly after its checks. The successful matrix is recorded at:
https://github.com/harshitgolakiya/studio-pro/actions/runs/37070302401

The Mac builds bundle LibreOffice, FFmpeg, Ghostscript, base English/multilingual
transcription, an English voice, speaker/isolation models, a CMYK profile, and
Spanish-to-English translation. Additional voices, OCR scripts, translation
pairs, and larger transcription models can be installed through Models.
Mac apps are ad-hoc signed. Apple Developer signing and notarization require
the account's certificate and credentials, which are not configured in this repo.

### Text-to-audio desktop update on 2026-10-03

The speech editor now reserves space for Generate speech at shorter window
heights and offers a dropdown of installed voices. Browse custom voice remains
available for paired Piper `.onnx` and `.onnx.json` files. Two focused UI tests
passed; the deployed executable showed all 13 voices and generated a real Amy
WAV, with Generate speech visible at 100%, 125%, and 150% display scaling.

Windows launch history identified an older Python 3.11 copy in
`C:\Program Files\Shadow Media Studio Pro`, without bundled models. The current
Python 3.12 app is deployed at `D:\Shadow-Agency-Studio\Shadow.exe`; the desktop
and user Start menu shortcuts named Shadow Agency Studio point to this version.
Its model, LibreOffice, and Ghostscript folders link to the existing assets in
`D:\Shadow-Agency-Studio-Build\vendor`, which must be retained. The previously
published Windows archive and Mac DMGs predate this desktop UI update.

### File-first workspace and audio preview on 2026-10-03

Shadow starts with file/folder selection and drag-and-drop. After import it shows
actions for the selected file types; selecting queue rows narrows the context.
Mixed inputs show how many files apply to each action. Conversion is separated
into images, video, audio, and documents and processes only that chosen subset.
Document batches expose their common output formats. Conversion settings appear
after choosing a conversion action, with image-only tabs hidden for other types.

Menu > All tools opens a searchable catalog with 65 entries, including all 40
existing processing actions and tools that do not require an input file.
Opening a tool carries the applicable queue inputs into its form. Studio pages
use direct sidebar navigation for OCR, data, archives, projects, integrations,
models, and engines instead of the nested More Tools menu. Imports now include
supported data, archive, subtitle, and print/font formats.

Voiceovers have Play, Stop, and a named output-device selector. Playback uses
the device's mix rate and resamples the preview without editing the saved WAV.
The reported exported voiceover files contained non-silent audio; Windows was
routing output to headphones. Packaged generation and playback on the laptop
speakers passed, with all 13 voices available. Generate and Play remained
visible in short windows at 100%, 125%, and 150% scaling.

The full source suite passed 452 tests in 308.457 seconds, with two seller-only
tests skipped. Packaged workspace checks passed file-only startup, contextual
audio tools, selected-input handoff, subtitle search, and routing of all 40
processing actions. Reports and screenshots are in
`D:\Shadow-Agency-Studio-Build\release\verification\workspace-*` and `speech-ui.*`.
The desktop app at `D:\Shadow-Agency-Studio` was updated using 13 changed/new
files (38,989,555 bytes), retaining the existing shared models and runtimes.
The previously published Windows archive and Mac DMGs still predate this update.

### Simplified tool navigation on 2026-10-03

The tool browser starts with eight illustrated categories instead of listing
all tools as large cards. Category contents and global search use compact action
rows. Video includes transcription and subtitle tools; document tools include
voiceovers and print delivery. Every catalog entry remains accessible.

Selecting one file shows its name and four primary actions. More actions expands
the rest; Change files replaces the selection and preserves it if the picker is
cancelled. The queue appears for multiple files or conversion settings. Repeated
category labels, descriptions, and input instructions were removed from action
rows. Fourteen focused workspace and media-visibility tests passed, including
complete category coverage and the collapsed/expanded file actions.

Native UI verification passed for all 65 catalog entries and all 40 Studio
action routes. The desktop installation at `D:\Shadow-Agency-Studio` received
two changed files (36,947,564 bytes); shared models and runtimes were retained.
Screenshots and the update manifest are in the release verification folder.
Published Windows archives and Mac DMGs still predate these UI changes.

### Cohesive desktop design on 2026-10-03

The desktop shell now has a permanent 204-pixel sidebar, compact top bar,
and a curated home with file import and three creation shortcuts. Tool
collections live in the sidebar; Explore offers common tools and global
search. Home preserves imported files. Preferences contains inline appearance
controls and access to local voices and engines. The native navigation popup
has been removed.

A graphite/violet and soft light palette, shared control styling, restrained
primary actions, Outfit headings, and consistent navigation carry through the
conversion settings and Studio forms. Single-file actions include a file
identity strip and short descriptions. Seventeen focused tests passed,
including sidebar navigation without losing the queue, eligible conversion
inputs, speech controls, and access to every catalog entry.

The staged native Windows build passed seven screenshot checks, including the
980x720 light layout, preferences, and the speech form with Generate speech
visible. All 65 catalog entries and 40 Studio action routes were verified.
The ready runtime is `D:\Shadow-Agency-Studio-Build\release\ui-fix\dist\Shadow`.
Its desktop update manifest and backup/install helper are in the release
verification folder (`premium-workspace-update-manifest.json` and
`premium_update.py`). The desktop copy at `D:\Shadow-Agency-Studio` was updated
after the user closed it: three files, 36,959,381 bytes, with backups and shared
assets retained. The installed executable passed the same native UI checks;
the desktop shortcut targets this copy. Published archives and Mac DMGs have
not been rebuilt.

### Palette consistency, tool organization and responsiveness on 2026-10-03

All twelve auxiliary windows now share the graphite/violet design tokens,
including the downloader, watch folder, license, recipes, optimizer charts,
format browser, image previews and command palette. Windows dialog title bars
follow the current theme, and new dialogs are centered within the display.
The queue table's selected colors also use the current palette. Warning and
failure states use new violet/rose roles rather than the old yellow/green/teal.

Collections have purpose-based sections and a deterministic action order.
Subtitle editing belongs to Video; text translation stays with documents.
Shared preview and audio tools appear in relevant collections. Shorter labels
and responsive wrapping prevent tool titles from clipping at smaller sizes.

Tool cards and headings are reused across navigation. Collection clicks render
once; search coalesces typing over 120ms and layout skips unchanged wrapping.
Scrollable panels share one wheel dispatcher per root, route to the nearest
panel, retain text-box/table scrolling, and animate coalesced movement with
cleanup on close. Tests cover stable bindings after repeated panel creation,
nested wheel routing, queued-animation cancellation, cached navigation,
ordered groups, search coalescing and legacy palette regressions.

The desktop update build reuses the existing shared assets. Packaging skips
Office temporary locks, including locks created by engine tests.

The engine-enabled full suite passed 461 tests with two skips. The packaged
runtime passed the five polish captures plus all workspace routes: every
catalog tool remains reachable, all 40 Studio actions open, and speech controls
remain visible. Native navigation measurements after warm-up were 76.13ms
median and 114.69ms maximum for the tested collections. Repeated dialog
creation/closure leaves the single wheel binding unchanged. Verification is in
`release/verification/ui-polish*` and `polish-*.png` under the build directory.
The ready desktop update is described by `ui-polish-update-manifest.json`;
`polish_update.py` backs up and replaces only changed runtime files after the
running application closes. Published archives and Mac DMGs remain unchanged.

All eleven real packaged-engine checks passed after the update build, including
PDF signing, encrypted delivery packages, Office export, transcription, OCR,
translation and project delivery. The desktop installation was updated after
the user closed Shadow: six files, 44,574,317 bytes, backed up under
`release/ui-fix/ui-polish-update-backup`. Models and shared engine folders were
retained. The desktop shortcut continues to target `D:\Shadow-Agency-Studio`.

Native checks on the installed desktop copy also passed: grouped Video tools,
minimum-window label fitting, updated dialog colors and stable wheel bindings.

### Conversion results experience

Completed conversions now show a compact results card above the queue. It
reports ready and failed counts, cancellations, elapsed time and space saved.
Conversion settings are hidden while reviewing results; Back to files returns
to file actions. Partial failures offer Retry failed and point to row details.
The output action opens the actual generated file for a single output, its
folder for a batch, or explicitly the first folder for multiple destinations.
Missing or moved outputs produce a helpful status message rather than opening
an unrelated destination. A new conversion or cleared queue resets the card.

Validation passed 32 focused workspace, batch-control, queue-store and palette
tests. Native staged and installed checks performed a real PNG-to-WebP
conversion and verified its dimensions, output opening, partial-failure and
cancellation states. Four minimum-size dark/light captures were reviewed.
The desktop update replaced two runtime files (36,970,111 bytes), retaining
shared engines and models, with backup under `release/ui-fix/results-update-backup`.
Receipts and captures are in `release/verification/results-*` in the build
directory. Published release archives remain unchanged.

### Favorite tools

Each tool row now has a star for saving a shortcut. Favorites has a dedicated
sidebar entry, keeps the user's saved order and scopes search to saved tools.
Explore tools shows favorites before its usual suggestions. Stars stay in sync
between collections and the Favorites view without rebuilding cached rows.
Favorites persist atomically through the existing settings store; unknown,
duplicate and malformed saved keys are ignored. If saving fails, shortcuts
remain available for the current session with an explanatory status message.

Validation passed 17 workspace tests and the palette regression check. Native
staged and installed checks saved favorites, restarted the executable, restored
their order, opened voiceover and conversion routes, carried selected inputs
through and removed all favorites. Four dark/light captures were reviewed at
the minimum window size. Test settings were isolated from user preferences.
The desktop update replaced two runtime files (36,971,940 bytes), with backup
under `release/ui-fix/favorites-update-backup`; shared engines/models were
retained. Receipts and captures are under `release/verification/favorites-*`.
Published release archives remain unchanged.

### Everyday tool search

Workspace search now recognizes common task phrases such as transcript,
voiceover, make video smaller, Word to PDF, unzip and remove noise. It ranks
exact names and phrases first, matches words regardless of order and tolerates
small typos or prefixes. Exact operation names preserve direction for Audio
to text versus Text to audio. Results include descriptions so users can choose
the intended tool. Favorites search and file-based actions retain their scope.
Search runs locally, reuses cached catalog metadata and keeps existing typing
debouncing; it introduces no service dependency.

Validation passed 23 tests covering phrase ranking, exact conversion direction,
word order, typos, scope, workspace flows and palette consistency. Staged native
checks passed search descriptions, Favorites scope and the voiceover route;
dark/light captures were reviewed at minimum window size. The ready desktop
update and backup procedure are recorded in `release/verification/search-*`
under the build directory. After the user closed Shadow, two runtime files
(36,976,018 bytes) were installed with backup under `release/ui-fix/search-update-backup`.
Native checks on the installed copy passed the same phrases, typo handling,
Favorites scope, descriptions and voiceover route. Shared engines/models and
published release archives remain unchanged.

### Natural offline voice upgrade

Added Kokoro v1.0 through the existing sherpa-onnx runtime, with ten curated
American/British English voices. Heart is the default when no voice preference
is saved. Existing Piper voices and custom ONNX voices remain usable. Voice
descriptors point to one shared model pack instead of duplicating neural weights
per voice. The Models catalog supports explicit installation/removal of this
self-contained pack; its original license is retained alongside the model.

Preview voice generates a short sample from the current script (or a sample
sentence) without a save dialog and plays it through the chosen output device.
Samples use a single overwriteable app-data cache. Synthesis keeps paragraph
and sentence boundaries, bounds long chunks, checks cancellation between native
sentences, validates PCM output and publishes WAVs through the existing atomic
output reservation. This is a naturalness upgrade; no artificial emotion labels
are exposed for a model that does not offer explicit emotional direction.

Focused tests passed (16 run, three optional engine skips). Staged and installed native
checks generated Heart, Michael and Emma samples, measured audible PCM levels,
verified spoken words through transcription, and checked the natural default,
preview autoplay and compact-window controls. The shared installed model pack
uses 382.7 MiB. The desktop runtime update replaced two files (36,982,375 bytes),
backed up under `release/ui-fix/natural-voice-update-backup`. Verification,
comparison WAVs and the UI capture are in `release/verification/natural-*` and
`piper-comparison.wav` in the build directory. Published archives are unchanged.

Model source: https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-multi-lang-v1_0.tar.bz2
Voice mapping: https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/kokoro.html

### Agency roles and read-only document refinement

The current voice picker contains only Heart (US female), Michael (US male),
Emma (UK female), and Daniel (UK male). The thirteen legacy Piper models and
six unused Kokoro descriptors were moved outside the active asset tree into
`release/verification/agency-retired-voices` for rollback. The shared Kokoro
weights remain one pack. Custom voice files can still be selected explicitly.

Explore tools now offers role shortcuts for design/production, video/social,
content/accounts, operations, and developers/IT. Every role retains access to
the full catalog. The role choice persists through the existing settings store.

Office layout preview no longer waits for text extraction; Text loads on request.
A local cache keeps up to 24 rendered files within 512 MiB and invalidates on
source path, size or modification time changes. XLSX/XLSM opens in a styled,
read-only sheet grid with selection, sheet switching and virtualized scrolling.
Pages supplies workbook charts/print layout. Presentations label navigation as
slides. Sources are not saved or changed. Saved formula values, third-party
layout rendering, substituted fonts and absent slide animations are documented
limits; this is not a replacement for the Microsoft Office rendering engine.

Focused workspace, speech, palette and preview checks passed. Staged and
installed native checks opened real DOCX/PPTX/XLSX fixtures, switched slides and
sheets, verified four voice choices and preserved source hashes. The staged Word
fixture took 15.77 seconds on first rendering and 0.22 seconds on cached reopen;
first-time rendering/import speed remains a release refinement. Screenshots and
receipts are under `release/verification/agency-*` in the build directory.
Two desktop runtime files (36,998,363 bytes) were installed with backup under
`release/ui-fix/agency-preview-update-backup`. Published release archives have
not been rebuilt. The remaining product work and no-required-paid-services
policy are recorded in [AGENCY_RELEASE_PLAN.md](AGENCY_RELEASE_PLAN.md).

### Campaign export sets

Projects & campaigns now includes Single preset, Social image set, Web + social
images, and Mixed client handoff. The social sets use existing 1080-square,
1080-by-1350 portrait and 1080-by-1920 story presets. Mixed handoff routes images
to WebP, video to MP4, documents to PDF and audio to WAV. These are general
delivery sizes, not promises about a platform's changing upload requirements.

Preview exports lists the intended relative filenames before processing. Each
campaign gets its own folder, preserving originals and earlier deliveries.
Saved profiles retain the export set, and the shared project-delivery action
uses it through both the UI and headless dispatcher. Existing single-preset
profiles and Current queue settings remain usable.

Per-output receipts persist successes, failures and hashes. Retry unfinished
and Resume export skip verified completed files and reject changed sources or
changed/missing completed outputs. Cancellation retains completed work. A ZIP
is created only after every planned export succeeds; packaging can be retried
independently. Variant folders, a public delivery index and checksums are
included. Internal receipts, local source paths and private settings are excluded.
Cropping currently centers each social image; manual crop positioning and
custom editable sets remain future refinements.

Validation passed 50 focused campaign, project, action-dispatch and workspace
tests (two optional engine skips). Staged native checks exercised saved-profile
dispatch, the preview UI, all three social sizes, ZIP checksum verification,
private receipt exclusion and resume without repeating completed conversions.
The ready desktop update changes two runtime files (37,009,253 bytes); its
manifest and captures are under `release/verification/campaign-*` in the build
directory. Shared engines/models and published release archives are unchanged.
