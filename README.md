# Shadow (v2.0.0)

A commercial-grade, native CustomTkinter desktop media conversion and compression suite for Windows. 100% offline, private, and blazingly fast.

![Shadow](assets/icon.ico)

---

## 🌟 Executive Overview

**Shadow** transforms traditional image compression into a complete multi-media studio designed for web designers, photographers, developers, video editors, and digital agencies. It eliminates the need for expensive online subscription services while keeping all files securely on the user's machine.

---

## 🚀 Key Features

### 1. Multi-Format Image Studio
- **Input Formats**: PNG, JPG, JPEG, BMP, TIFF, TIF, ICO, WEBP.
- **Output Formats**:
  - **WEBP**: High-efficiency lossy and lossless compression with alpha channel preservation.
  - **JPG / JPEG**: Optimized progressive JPEGs with fine-tuned quality control.
  - **PNG**: Lossless image compression with RGBA transparency.
  - **ICO**: Multi-resolution Windows application & website favicon generation (16x16, 32x32, 48x48, 64x64, 128x128, 256x256).
  - **PDF Binder**: Convert single images or merge an entire batch of images into a single multi-page PDF document.

### 2. Video & Audio Engine (Powered by FFmpeg & Hardware GPU)
- **Input Media**: MP4, MKV, MOV, AVI, WEBM, FLV, MP3, WAV, AAC, OGG, M4A, OPUS.
- **Hardware Acceleration**: Auto-detects Intel QuickSync (`h264_qsv`), NVIDIA NVENC (`h264_nvenc`), and AMD AMF (`h264_amf`) for blazing fast encoding, with graceful CPU fallback.
- **Output Video**:
  - **WebM**: Modern VP9 video codec with Opus audio encoding for web streaming.
  - **MP4**: Universal H.264 video with AAC audio for cross-device compatibility.
  - **Animated WebP**: Multi-frame animated conversion from GIF and video clips, preserving timing and transparency.
  - **GIF**: Clean animated GIF generation with optimized color palettes.
- **Lossless Video Trimmer**: High-speed clip cutter using sub-second stream copying without re-encoding quality loss.
- **Audio Extraction & Compression**: Extract and convert audio tracks directly into MP3, AAC, Opus, or WAV.

### 3. Personal Media Stream Downloader (VIP Power Feature)
- Dedicated offline media downloader for offline viewing.
- Unlocked exclusively with the VIP Master Key.
- Download presets: **4K Ultra HD (2160p)**, **1080p Full HD**, **720p HD**, **480p SD**, or standalone high-fidelity audio tracks (**320 kbps Studio**, **192 kbps High**, **128 kbps Standard**).
- Automatically queues downloaded files into the media engine for instant conversion or trimming.

### 4. Smart Sizer (Target Size Solver)
- Automatically computes optimal quality parameters using a binary search quality solver.
- Simply specify your target file size in **KB** or **MB** (e.g. `200 KB` for web banners or `5 MB` for email attachments), and the engine will iteratively converge on the target size.

### 5. Pro Batch Watermarking (Text & Image Logo)
- Protect your creative assets with custom text or high-resolution PNG/JPEG logo watermarking.
- Supports 5 anchor positions: **Bottom-Right**, **Bottom-Left**, **Top-Right**, **Top-Left**, and **Center**.
- Includes automatic contrast drop-shadows, proportional aspect-ratio scaling (5%-50%), and configurable alpha opacity.

### 6. Auto-Watch Folder Background Pipeline
- Background daemon monitoring incoming folders.
- Automatic file write debounce stabilization so files being transferred are safely processed once completed.
- Continuous auto-compression into your chosen format and destination.

### 7. Interactive Visual Diff Split Slider & Inspector
- Double-click any row or select **Preview & Compare** from the context menu.
- Interactive mouse-draggable curtain slider comparing Original vs Compressed in real-time.
- Amplified 10x Difference Map highlighting exact compression compression artifacts.
- Real-time display of dimensions, file sizes, and percentage savings.

### 8. Animated GIF to High-Efficiency WebP Converter
- Converts heavy, legacy animated GIFs into compact, modern animated WebP files.
- Preserves all animation frames, custom millisecond delay durations, transparency, and infinite loops.
- Delivers up to 80-90% file size reductions.

### 9. Resolution & Scale Controls
- **Max Dimension Resizing**: Constrain images to maximum bounding dimensions (e.g. `1920px`, `1200px`) while strictly preserving aspect ratio.
- **Scale Percentage**: Scale entire image batches by relative percentages (e.g. `50%`, `75%`).
- By default, original resolution is always maintained (1:1).

### 10. Privacy & SEO Engine
- **EXIF & GPS Scrubber**: Strip sensitive metadata (camera serial, GPS coordinates, capture date/time) before publishing online.
- **Metadata Preservation**: Retain camera color profiles (ICC) and EXIF data when required for photography workflows.
- **SEO Filename Slugifier**: Convert messy file names into clean, URL-friendly kebab-case strings (e.g., `IMG_2026 09 14 (Copy).jpg` -> `img-2026-09-14-copy.webp`).

### 11. Windows Explorer Shell Integration
- Seamless right-click context menu integration in Windows Explorer:
  - Right-click any supported file -> **"Compress with Shadow"**
  - Right-click any folder -> **"Compress folder with Shadow"**
- Ingests selected items directly into the compression queue on launch.

### 12. Commercial Licensing & Trial Mode
- **Free Trial Mode**: Allows processing up to 5 items per batch with full access to all features.
- **Pro Lifetime License**: Unlocks unlimited batch processing with an Ed25519-signed offline license key.
- License keys are verified with public-key cryptography: the shipped app only ever contains the *public* key (`licensing.py`), so it can check a key's signature but cannot forge new ones. Real keys are produced with `keygen_tool.py`, a seller-only script that holds the private signing key and **must never be distributed** (it is excluded from the PyInstaller build and from `.gitignore`).
  ```powershell
  python keygen_tool.py pro --note "buyer@example.com"
  python keygen_tool.py vip --note "internal test"
  ```
  Each generated key is logged locally to `sales_log.csv` for your own records.
- Built-in license key validator and activation modal dialog (paste the full key; it's a long signed token, not a short serial).

### 13. Enterprise Audit & Reporting
- Export full conversion sessions to standard **CSV spreadsheets** with original size, converted size, bytes saved, compression ratio, resolution, and output paths.

### 14. Document ↔ Markdown Converter
- Convert **DOCX, PDF, HTML, and TXT** documents into clean **Markdown**, and convert Markdown back out to **DOCX, PDF, HTML, or TXT**.
- Preserves headings, bold/italic text, and bullet/numbered lists in both directions.
- PDF text extraction is best-effort (works well for normal text PDFs; scanned/image-only PDFs have no extractable text and will report an error rather than silently producing an empty file).
- Runs through the same batch queue, destination folder, renaming, and overwrite-protection rules as image/video conversions.

### 15. Persistent Preferences
- Automatically remembers your selected output directory, theme, quality preset, resize settings, watermark text, and audio/video preferences across app restarts in `%APPDATA%\Shadow\settings.json`.

---

## 🛠️ Installation & Setup

### Requirements
- Windows 10 / 11 (64-bit)
- Python 3.10+ (for source installation)
- FFmpeg: bundled automatically in the packaged .exe/installer (see below), so
  end users never need to install it separately. Running from source instead
  needs a local copy in `vendor\ffmpeg\` (fetched with `fetch_ffmpeg.ps1`) or
  FFmpeg on your system PATH.

### Install from Source
```powershell
git clone <repository_url>
cd webp-compressor
python -m venv ..\.venv
..\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\fetch_ffmpeg.ps1   # one-time, ~200MB
```

### Run the App
```powershell
python main.py
```

---

## 📦 Building the Standalone Executable & Installer

### 1. Fetch bundled FFmpeg (one-time, or whenever you want to update it)
```powershell
powershell -ExecutionPolicy Bypass -File .\fetch_ffmpeg.ps1
```
Downloads the FFmpeg "essentials" build into `vendor\ffmpeg\`. It's GPLv3-licensed;
the app invokes it as a separate subprocess (never linked into the Python code) and
ships its LICENSE file alongside it -- see `EULA.txt` for the attribution notice.

### 2. Build Executable (`PyInstaller`)
```powershell
python -m PyInstaller --clean "Shadow.spec"
```
Produces a **folder** build at `dist\Shadow\` (onedir, not onefile) with
`Shadow.exe` plus the bundled FFmpeg binaries under `_internal\bin\`. Onedir is
used instead of a single-file exe because the ~200MB of bundled FFmpeg binaries
would otherwise be re-extracted to a temp folder on every single launch.

### 3. Build Windows Setup Installer (`Inno Setup 6`)
```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
```
The setup wizard installer will be generated at `installer\Shadow-Media-Studio-Setup.exe`
(~75MB compressed).

### 4. One-Click Release Pipeline
Run the included release script to execute the full unit test suite, compile the executable, and build the installer package:
```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

---

## 🍎 macOS Build

Shadow also runs on macOS, but **PyInstaller cannot cross-compile** -- a
`.app`/`.dmg` has to be built while actually running on macOS. Two ways to
get one:

### Option A: GitHub Actions (no Mac required)
`.github/workflows/build-macos.yml` builds Intel and Apple Silicon DMGs on
GitHub's hosted macOS runners.
- **Manual run**: open the repo on GitHub -> Actions -> "Build macOS App" -> Run workflow.
- **Automatic on release**: push a version tag, e.g. `git tag v2.0.0 && git push --tags`,
  which also attaches both DMGs to a GitHub Release.
- Download the `Shadow-macOS-apple-silicon` or `Shadow-macOS-intel` artifact from the run.
  The apple-silicon build is arm64 and covers every Apple-chip Mac: the M-series
  (M1 onward) as well as the A18 Pro-based MacBook Neo. Only pre-2020 Intel Macs
  need the intel build.

### Option B: Build locally on a Mac
```bash
git clone <repository_url>
cd webp-compressor
python3 -m venv ../.venv
source ../.venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
mkdir -p vendor/ffmpeg-mac
cp "$(command -v ffmpeg)" vendor/ffmpeg-mac/ffmpeg
cp "$(command -v ffprobe)" vendor/ffmpeg-mac/ffprobe

python -m unittest discover -s tests -p "test_*.py" -v
python -m PyInstaller --clean Shadow-mac.spec
```
This produces `dist/Shadow.app`. To package it as a DMG:
```bash
mkdir -p installer dmg_staging
cp -R dist/Shadow.app dmg_staging/
ln -s /Applications dmg_staging/Applications
hdiutil create -volname "Shadow Media Studio Pro" -srcfolder dmg_staging \
  -ov -format UDZO installer/Shadow-Media-Studio-Setup.dmg
```

### Gatekeeper warning (unsigned build)
This build isn't code-signed or notarized (that requires a paid Apple
Developer account). On first launch, macOS will refuse to open it via a
normal double-click. To run it anyway:
- Right-click (or Control-click) `Shadow.app` -> **Open** -> **Open** again in the dialog, or
- Run `xattr -cr /Applications/Shadow.app` in Terminal after installing.

Signing and notarizing for a friction-free install is a separate step --
it needs an Apple Developer Program membership and a Developer ID
certificate; ask if you want the workflow extended to do that.

---

## 🧪 Automated Testing

MediaCompressor Studio Pro includes automated test coverage covering all conversion engines, licensing cryptography, watermark generation, and media conversion:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

All 55 automated tests pass cleanly with zero external network requirements.

---

## 📄 License & Privacy Guarantee

- **100% Offline**: Zero telemetry, zero analytics, zero external network requests.
- **Secure**: All transformations occur in-memory or directly on local disk storage.
- **Fonts**: The UI uses Inter (body text) and Outfit (headings), both bundled in `assets/fonts/` and registered as process-private fonts at startup (see `font_loader.py`) so rendering doesn't depend on what's installed on the customer's machine. Both are SIL Open Font License fonts from Google Fonts; their `OFL-*.txt` license files ship alongside them.
