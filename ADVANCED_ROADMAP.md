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
- [ ] Pixel inspector with coordinates and RGBA values.
- [ ] Gamut clipping, alpha, and metadata-loss warnings.
- [ ] Multi-variant comparison: compare several codecs/qualities at once.

## Intelligent optimizer

- [-] Optimize for a requested maximum size while protecting visual quality
      (engine: `optimizer.optimize_for_size` with an SSIM floor; not yet surfaced in the
      Smart Sizer UI, which still solves for size alone).
- [-] Optimize for a perceptual-quality target (engine: `optimizer.optimize_for_quality`;
      no UI entry point yet).
- [x] Automatically compare WebP, AVIF, HEIC, JPEG, and JPEG 2000 (Optimize button;
      dialog sweeps the first four by default, JPEG 2000 is available in the engine).
- [-] Add SSIM and Butteraugli-style perceptual scoring (block-SSIM and PSNR done in
      pure Pillow; no Butteraugli).
- [x] Display a Pareto frontier of quality versus file size.
- [-] Recommend the best codec using image content, alpha, animation, and destination
      (content kind, alpha and destination are used; animation is detected but not yet
      weighted).
- [ ] Learn optional per-user preferences without uploading media.

## Non-destructive processing recipes

- [ ] Represent operations as a visible, reorderable processing stack.
- [x] Save, load, duplicate, import, and export recipe JSON files.
- [x] Add versioned recipe migrations.
- [ ] Add per-file overrides inside a batch.
- [ ] Copy/paste processing settings between queued files.
- [ ] Add undo/redo for recipe and queue edits.
- [ ] Add conditional steps such as “resize only above 4K.”

## Professional color and format pipeline

- [ ] Add explicit ICC input/output profile selection.
- [ ] Add sRGB, Display-P3, Adobe RGB, and CMYK conversion workflows.
- [ ] Add 10/12/16-bit processing where the codec supports it.
- [ ] Add HDR transfer functions and tone mapping.
- [ ] Add camera RAW development through a dedicated RAW engine.
- [ ] Add SVG rasterization with selectable scale and background.
- [ ] Add JPEG XL input/output.
- [ ] Add PSD layer-selection and compositing controls.

## Queue, performance, and reliability

- [x] Persist the queue and restore it after restart or crash.
- [ ] Pause and resume individual jobs or the whole queue.
- [ ] Retry failed jobs with editable settings.
- [ ] Add job priorities, duplicate detection, and dependency rules.
- [ ] Add conversion history with searchable logs and reproducible settings.
- [ ] Add CPU, GPU, memory, throughput, and ETA telemetry.
- [ ] Tune worker concurrency automatically from workload and memory pressure.
- [ ] Add safe disk-space preflight and temporary-file cleanup.
- [ ] Add structured logs and one-click diagnostics export.

## Automation and extensibility

- [x] Basic watched-folder conversion.
- [x] Basic command-line file ingestion.
- [ ] Add rule-based watched folders with recipes and routing conditions.
- [ ] Add a complete headless CLI with machine-readable progress and exit codes.
- [ ] Add a local automation API.
- [ ] Add a documented plugin SDK for codecs, processors, and exporters.
- [ ] Add workflow hooks before/after each job.
- [ ] Add integrations for design and publishing workflows.

## Shipping quality

- [x] Automated converter regression suite.
- [x] Windows PyInstaller packaging verification.
- [ ] Add golden-image visual regression fixtures per codec and platform.
- [ ] Add packaged-app smoke tests on Windows, Intel macOS, and Apple Silicon.
- [ ] Sign the Windows installer and application binaries.
- [ ] Sign and notarize macOS applications and DMGs.
- [ ] Add secure automatic updates with rollback.
- [ ] Add opt-in crash reporting with privacy controls.
- [ ] Add performance benchmarks and release-to-release regression limits.

## Resume order

1. Retry failed jobs with editable settings; pause/resume the queue.
2. Surface the optimizer's SSIM floor in the Smart Sizer and add a quality-target mode.
3. Represent operations as a visible processing stack (recipes already carry the data).
4. Conversion history with searchable logs; structured diagnostics export.

## Current verification baseline

- Unit/integration tests: 112 passing after the format browser, versioned recipes,
  queue recovery, the optimizer, density modes and the command palette
  (`tests/test_format_browser.py`, `tests/test_recipes.py`, `tests/test_queue_store.py`,
  `tests/test_optimizer.py`, `tests/test_command_palette.py` drive the real window).
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
