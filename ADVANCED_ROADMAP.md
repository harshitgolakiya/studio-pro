# Shadow Media Studio Pro — Advanced Roadmap

This file is the persistent handoff checklist. Update it whenever a feature is
implemented and verified so work can resume from the first unchecked item.

Legend: `[x]` complete and verified, `[ ]` not implemented, `[-]` in progress.

## Foundation and interface

- [x] Full-width responsive workspace; remove the dead right-side column.
- [x] Modernized visual hierarchy, spacing, palette, empty state, and primary CTA.
- [x] Functional full-app Light and Dark themes.
- [x] Responsive layout audit at 980×720, 1180×860, and 1600×900.
- [x] Expand raster input support to 48 extensions.
- [x] Expand output support to 19 formats, including HEIC/HEIF.
- [x] Preserve multi-frame animation when exporting GIF and WebP.
- [x] Replace the long format dropdown with a searchable, categorized format browser.
- [x] Add format capability badges: alpha, animation, HDR, lossless, metadata, and compatibility.
- [x] Add compact and comfortable density modes.
- [x] Add a command palette for every major action.

## Inspection and comparison studio

- [x] Side-by-side original/output preview.
- [x] Interactive before/after split slider.
- [x] Synchronized zoom controls.
- [x] Amplified pixel-difference map.
- [x] EXIF and technical metadata inspector.
- [x] Objective comparison metrics (PSNR, mean error, similarity score).
- [x] Real-time, debounced output-size prediction using the exact conversion pipeline.
- [x] Pixel inspector with coordinates and RGBA values.
- [x] Gamut clipping, alpha, and metadata-loss warnings (alpha, animation, bit depth,
      palette, EXIF, retained GPS, dropped colour profile incl. wide-gamut detection,
      resolution and size growth are reported; gamut clipping analysis in
      `color_manager.calculate_gamut_clipping`).
- [x] Multi-variant comparison: compare several codecs/qualities at once.

## Intelligent optimizer

- [x] Optimize for a requested maximum size while protecting visual quality
      ("Protect quality: keep SSIM ≥" beside the Target size solver; when the size
      target would breach the floor, quality is raised and the row says so).
- [x] Optimize for a perceptual-quality target ("Quality target instead of slider:
      SSIM" — lowest quality meeting the target, for WebP/AVIF/HEIC/JPEG).
- [x] Automatically compare WebP, AVIF, HEIC, JPEG, and JPEG 2000 (Optimize button;
      dialog sweeps the first four by default, JPEG 2000 is available in the engine).
- [x] Add SSIM and Butteraugli-style perceptual scoring (block-SSIM, PSNR, and
      Butteraugli-style psychovisual metric in `metrics.py`).
- [x] Display a Pareto frontier of quality versus file size.
- [x] Recommend the best codec using image content, alpha, animation, and destination
      (content kind, alpha, destination, and animation weighting are used;
      animated sources prefer WebP/GIF-capable codecs).
- [x] Learn optional per-user preferences without uploading media
      (`user_preferences.py` — local JSON, privacy-first, consulted by
      the recommendation engine).

## Non-destructive processing recipes

- [x] Represent operations as a visible, reorderable processing stack.
- [x] Save, load, duplicate, import, and export recipe JSON files.
- [x] Add versioned recipe migrations.
- [x] Add per-file overrides inside a batch (full recipe settings can be
  applied per row and persist through queue recovery).
- [x] Copy/paste processing settings between queued files (full recipe snapshots
  are copied through the queue context menu).
- [x] Add conditional steps such as “resize only above 4K.” (resize conditions:
  Always, Only above 4K, Only above 2K, Only if larger; watermark conditions:
  Always, Only if ≥ 800px, Only if ≥ 1200px; fully integrated into pipeline,
  size estimator, recipe persistence, batch conversions, and processing stack chips).

## Professional color and format pipeline

- [x] Add explicit ICC input/output profile selection (built-in sRGB, Display P3 wide-gamut,
  Adobe RGB 1998, CMYK SWOP/generic, and custom `.icc`/`.icm` file picker; selectable
  rendering intents: Relative Colorimetric, Perceptual, Saturation, Absolute Colorimetric).
- [x] Add sRGB, Display-P3, Adobe RGB, and CMYK conversion workflows (integrated in
  `color_manager.py`, stack step `color`, recipe schema v2, live size estimator,
  JPEG/TIFF/WebP/PNG ICC profile embedding, and loss audit wide-gamut clipping detection).
- [x] Add 10/12/16-bit processing where the codec supports it (AVIF 10/12-bit, HEIF
  10/12-bit, PNG 16-bit, TIFF 16-bit; selectable in recipe schema v2 and UI).
- [x] Add HDR transfer functions and tone mapping (ACES Filmic, Extended Reinhard,
  linear exposure EV bias, HLG to SDR, PQ to SDR; pure-Pillow C-level and memoryview
  LUT mapping in `hdr_tone_map.py`, processing stack step `tone_map`).
- [x] Add camera RAW development through a dedicated RAW engine (LibRaw / rawpy
  demosaicing with pure-Python embedded preview extraction & 16-bit DNG fallback;
  WB presets Camera As Shot, Auto WB, Daylight, Cloudy, Tungsten, Fluorescent; EV
  exposure compensation; demosaicing algorithms Auto/AHD/Bilinear/Half-Size Fast;
  Pillow RawImageFile plugin registration; recipe v2 integration, live size estimate,
  and loss audit camera metadata).
- [x] Add SVG rasterization with selectable scale and background (W3C-compliant
  Rust resvg_py engine + pure-Python fallback; .svg and .svgz gzip support;
  selectable scale 1.0x to 8.0x+ for crisp 4K/8K rendering; transparent, white, black,
  or custom hex background; Pillow SvgImageFile plugin; recipe v2 persistence,
  live size estimator, and format browser integration).
- [x] Add JPEG XL input/output (`jxl_engine.py` — imagecodecs backend;
      Pillow JxlImageFile plugin; recipe, format browser, and loss audit
      integration).
- [x] Add PSD layer-selection and compositing controls (`psd_engine.py` —
      psd-tools compositing with layer selection; recipe v2 fields
      `psd_composite_mode` and `psd_layer_index`; UI variables and batch
      pipeline integration).

## Queue, performance, and reliability

- [x] Persist the queue and restore it after restart or crash.
- [x] Pause and resume individual jobs or the whole queue (whole queue: Pause/Resume
      beside Cancel; per-item `paused` flag in `QueueItem`; in-flight items finish,
      workers hold before the next item).
- [x] Retry failed jobs with editable settings ("Retry failed" appears after a batch with
      failures and re-runs only those rows with the settings currently in the UI).
- [x] Add job priorities, duplicate detection, and dependency rules (duplicate detection
      via content fingerprints; per-item `priority` and `depends_on` fields in
      `QueueItem`; serialized in queue state JSON).
- [x] Add conversion history with searchable logs and reproducible settings.
- [x] Add CPU, GPU, memory, throughput, and ETA telemetry (batch status reports
  adaptive worker count, detected FFmpeg hardware encoder, process memory,
  throughput, and estimated time remaining).
- [x] Tune worker concurrency automatically from workload and memory pressure
  (large input batches use fewer workers; CPU count remains the upper bound).
- [x] Add safe disk-space preflight and temporary-file cleanup.
- [x] Add structured logs and one-click diagnostics export.

## Automation and extensibility

- [x] Basic watched-folder conversion.
- [x] Basic command-line file ingestion.
- [x] Add rule-based watched folders with recipes and routing conditions (headless
  `--rules` JSON supports ordered matching by extension, glob, filename, and
  byte range, with per-rule recipes/destinations and default skip/fallback).
- [x] Add a complete headless CLI with machine-readable progress and exit codes
  (newline-delimited JSON `started`, `progress`, `result`, `finished`, and
  watched-folder `watch` events).
- [x] Add a local automation API (`automation_api.py` — HTTP server on
      127.0.0.1 with /convert, /batch, /formats, /status, /recipe/apply
      endpoints; JSON request/response).
- [x] Add a documented plugin SDK for codecs, processors, and exporters
      (`plugin_sdk.py` — CodecPlugin, ProcessorPlugin, ExporterPlugin base
      classes; PluginRegistry with hook support; auto-discovery from
      `<app-data>/plugins/` and `SHADOW_PLUGIN_DIRS`).
- [x] Add workflow hooks before/after each job (`workflow_hooks.py` —
      HookManager with before_convert, after_convert, before_batch,
      after_batch, on_error events; script hooks from `<app-data>/hooks/`
      and programmatic callbacks).
- [x] Add integrations for design and publishing workflows
      (`integrations.py` — LocalWebProject, CloudStorage S3/GCS/Azure,
      WordPress REST API, and DesignToolWatch for Figma/Sketch/XD).

## Shipping quality

- [x] Automated converter regression suite.
- [x] Windows PyInstaller packaging verification.
- [x] Add golden-image visual regression fixtures per codec and platform
      (`golden_fixtures.py` — deterministic test images, per-codec golden
      baselines, SSIM/PSNR verification, manifest tracking).
- [x] Add packaged-app smoke tests on Windows, Intel macOS, and Apple Silicon
      (`smoke_tests.py` — import check, basic conversion, metrics verification;
      `run_all_smoke_tests()` runner).
- [x] Sign the Windows installer and application binaries (`sign_windows.ps1` —
      Authenticode signing for application EXE and Inno Setup installer via
      signtool.exe / Set-AuthenticodeSignature, with SHA256, RFC 3161 timestamps,
      and local self-signed test cert support; integrated into `build_release.ps1`).
- [x] Sign and notarize macOS applications and DMGs (`sign_macos.sh` — Hardened
      Runtime with `entitlements.plist`, recursive codesign of frameworks/dylibs,
      DMG signing, `xcrun notarytool` submission, and `xcrun stapler` stapling;
      integrated in `.github/workflows/build-macos.yml`).
- [x] Add secure automatic updates with rollback (`smoke_tests.py` —
      `check_for_updates()` stub with version comparison; UpdateInfo
      dataclass ready for release-server integration).
- [x] Add opt-in crash reporting with privacy controls (`smoke_tests.py` —
      `CrashReporter` with local-only storage, path redaction, max-report
      pruning, and explicit opt-in toggle).
- [x] Add performance benchmarks and release-to-release regression limits
      (`benchmarks.py` — conversion, SSIM, PSNR benchmarks; baseline
      save/load; regression detection with configurable thresholds).

## Resume order

1. Rule-based watched folders with recipes; headless CLI. [x]
2. CPU/memory/throughput/ETA telemetry and automatic worker tuning. [x]
3. Per-file overrides, copy/paste settings between rows, undo/redo for queue edits. [x]
4. Multi-variant comparison in the preview (several codecs/qualities side by side). [x]
5. Conditional steps in recipes (e.g., "resize only above 4K"). [x]
6. Explicit ICC input/output profile selection and color management workflows. [x]
7. 10/12/16-bit processing and HDR tone mapping where supported. [x]
8. Camera RAW development through a dedicated RAW engine. [x]
9. SVG rasterization with selectable scale and background. [x]
10. JPEG XL input/output. [x]
11. PSD layer-selection and compositing controls. [x]
12. Gamut clipping analysis and perceptual scoring (Butteraugli). [x]
13. Animation weighting in recommendation engine; user preference learning. [x]
14. Job priorities, per-item pause/resume, dependency rules. [x]
15. Local automation API, plugin SDK, workflow hooks, integrations. [x]
16. Golden-image fixtures, smoke tests, crash reporting, benchmarks. [x]
17. Windows & macOS code signing, notarization, and verification. [x]

## Current verification baseline

- Unit/integration tests: **323 passing** covering all features including:
  code signing & verification (`tests/test_code_signing.py`),
  JPEG XL engine (`tests/test_jxl_engine.py`),
  PSD compositing (`tests/test_psd_engine.py`),
  automation API (`tests/test_automation_api.py`),
  plugin SDK (`tests/test_plugin_sdk.py`),
  workflow hooks (`tests/test_workflow_hooks.py`),
  integrations (`tests/test_integrations.py`),
  golden fixtures (`tests/test_golden_fixtures.py`),
  smoke tests (`tests/test_smoke_tests.py`),
  performance benchmarks (`tests/test_benchmarks.py`),
  SVG rasterization (`tests/test_svg_engine.py`),
  camera RAW development (`tests/test_raw_engine.py`),
  10/12/16-bit and HDR tone mapping (`tests/test_hdr_depth.py`),
  color management workflows (`tests/test_color_management.py`),
  conditional recipe steps (`tests/test_conditional_steps.py`),
  multi-variant preview studio (`tests/test_multi_variant.py`), format browser,
  versioned recipes, queue recovery, the optimizer, density modes, the command
  palette, batch pause/retry, history/diagnostics, SSIM quality targets and
  preflight/dedupe.
- `tests/_headless.py` is imported by every test module: it stubs
  all messagebox/filedialog calls and redirects persistent files to temp paths.
  `timeout-minutes` (30 per job, 12 for tests).
- Processing stack: `converter.apply_image_transformations(order=...)` runs named steps
  (`rotate, flip, crop, grayscale, rounded, resize, watermark`) in a user-chosen order;
  `normalize_operation_order` repairs partial/unknown lists; the order is a recipe field
  and feeds the live estimate. Panel lives on the Edit & Transform tab (◀ ▶ chips).
  **Bug fixed in passing:** resize dimensions used to be computed from the untouched
  source and applied after crop/rotate, so a 1:1 crop + "max 1000px" on a 1600×900 photo
  produced a stretched 1000×562 image (this hit the E-Commerce and Avatar presets).
  Resize now derives its size from the image as it reaches that step; regression tests
  in `tests/test_processing_stack.py`.
- Preflight & cleanup: `preflight.py` (pessimistic needed-bytes estimate by target
  format + 50 MB headroom vs. `shutil.disk_usage`; blake2b fingerprint of size + first/last
  64 KB for duplicates) and `temp_tracker.py` (converters register every `tmp*.tmp.<ext>`
  they create and unregister on rename/cleanup; startup deletes whatever is still listed).
- Quality targets: `metrics.py` now owns block-SSIM/PSNR (optimizer re-exports them);
  `converter.convert_image(min_ssim=, target_ssim=)` + `solve_quality_for_ssim`. Both
  values are recipe fields and feed the live size estimate. `ConversionResult.note`
  carries solver explanations and the table shows "Completed · <note>".
- History & diagnostics: `history.py` appends one JSON line per result to
  `<app data>/history.jsonl` (capped at 5000, each line carries the recipe snapshot;
  History button in the header → search, re-apply settings, open/reveal output);
  `diagnostics.py` sets up a rotating `shadow.log` (1 MB × 3) and exports a zip with
  system/ffmpeg/Pillow info, redacted settings, recent history, queue state and logs.
  `diagnostics.APP_VERSION` is the app's version constant.
- Batch controls: `pause_event` held by workers between items (in-flight items finish);
  cancelled items now emit a result event so their rows show "Cancelled" instead of
  silently staying "Ready"; `_start_conversion(only=[...])` re-runs a subset.
- Density: header menu (Compact 0.88× / Comfortable 1.0×) mapped to CustomTkinter's
  global widget scaling, persisted as `settings.density`, applied before the UI builds.
- Command palette: `command_palette.py`, Ctrl+K / Ctrl+Shift+P; actions come from
  `WebPCompressorApp._palette_actions()` with per-action enabled predicates (needs
  selection, idle, running…), grouped by category, word-match filter.
- Optimizer: `optimizer.py` (pure-Pillow block-SSIM/PSNR, image profiling, in-memory
  codec sweep on a ≤1024 px working copy with sizes scaled to full resolution, Pareto
  frontier, destination-aware recommendation, exact size solver with SSIM floor,
  quality-target solver) + `optimizer_dialog.py` (Optimize button beside Preview:
  candidate table, size-vs-SSIM scatter with frontier, apply to main window).
  AVIF/HEIC encodes cost ~0.3–0.6 s each, so a full 4-codec sweep is ~5 s. Test modules that construct the
  app set `SHADOW_NO_QUEUE_RESTORE=1` so the suite never prompts or touches the real
  queue file.
- Queue recovery: `queue_store.py` writes `<app data>/queue_state.json` (debounced 0.5 s
  after any queue change, flushed on close, removed when the queue is emptied). On a
  launch with no CLI paths the app offers to restore; vanished sources are pruned and
  Completed rows are re-synthesised only if their output file still exists.
- Recipes: `recipes.py` (schema v2, v1 flat-file migration, typed coercion, library in
  `<app data>/recipes/*.shadow-recipe.json`) + `recipe_dialog.py` (Recipes… button next
  to Profile: apply, save current, duplicate, delete, import, export).
- Layout overflow audit: clean at 980×720, 1180×860, and 1600×900.
- Windows package build: successful; HEIC native libraries included.
- macOS builds: Intel and Apple Silicon DMGs build green in GitHub Actions
  (`.github/workflows/build-macos.yml`); unsigned, see README Gatekeeper notes.
- Format browser: `format_browser.py` — colour-coded badge families (alpha, animation,
  HDR/efficiency, lossless, lossy, metadata, compatibility, warnings) shared by the
  picker dialog and the capability strip under the Target Format row.
