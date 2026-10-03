# Shadow: agency-wide release plan

Shadow is a local workspace for preparing, reviewing and delivering agency
files. Its commercial value should come from reliable workflows and saved
time. The core must not depend on paid AI, cloud or platform APIs. Optional
online connections require a documented free tier or agency-owned server;
limits and account requirements must be visible before connection.

## Teams and workflow coverage

| Team | Existing useful workflows | Priority gaps for a sellable release |
| --- | --- | --- |
| Designers and production | Image conversion/resize/watermarks, codec comparison, CMYK, font inspection, PDF preflight, client brand kits | Named channel export presets; visual checks against brand rules; batch before/after review |
| Video editors and social media | Video conversion/compression/trim, audio cleanup, transcription, subtitle editing, voiceovers | Platform export presets; safe-area overlays; reusable campaign export sets; clearer preview and playback |
| Copywriters and content | Office/PDF viewing and conversion, OCR, transcription, text translation, read-aloud voices | Script/caption templates; document search; visible version comparisons |
| Account and project managers | Client projects, saved recipes, naming rules, delivery packages and checksums | Campaign workspace; milestones; local review comments and approvals; client handoff receipts |
| Media buyers and analysts | Data conversion, deduplication, schema validation, worksheet export | Repeatable campaign-report cleanup; saved column mappings; report comparison |
| Operations and finance | Office/PDF workflows, forms, spreadsheet inspection, manifests, archives | Folder intake rules; reusable document checklists; clearer failure recovery and history |
| Developers and IT | JSON/data schemas, validation, archive inspection, manifests, folder automation, plugin/hooks/loopback API | Friendly API setup/docs; health diagnostics; reliable upgrades; configuration export and restore |
| Agency owners | License UI, client presets, local file processing | Transparent feature/edition boundaries; stable installers; onboarding; recovery documentation |

Role shortcuts are implemented for Design & production, Video & social,
Content & accounts, Operations, and Developers & IT. These are entry points
into actual tools, not access restrictions. All teams retain the full catalog.

## Current refinement delivery

- Four English voices: US female/male and UK female/male. Existing multilingual
  transcription and translation remain separate capabilities.
- Document layout appears before text extraction. Text loads on request.
- Rendered Office previews are cached and invalidated when a file changes;
  the cache is bounded by item count and disk usage.
- Workbooks open directly in a read-only, styled sheet grid with cell selection,
  sheet navigation and virtualized scrolling. Saved formula results are shown;
  the grid is not an Excel calculation engine. Pages supplies charts/print layout.
- Presentations use slide navigation and retain the rendered slide layout.
- Previewing and navigation never save changes to the source document.
- Campaign export sets now produce square/portrait/story image variants or a
  mixed image/video/document/audio handoff. Projects save the set; Preview exports
  lists intended files. Each run has a separate folder and a durable receipt.
  Retry/resume skips verified successful outputs and rejects changed sources.
  Optional delivery ZIPs retain variant folders and include a public index plus
  checksums; internal source paths and project settings stay out of the ZIP.

Bundled LibreOffice provides offline layout rendering. Exact Microsoft Office
pixel parity, font substitutions, animation playback and advanced workbook
calculation are not promised. The app keeps an Open in default app action for
original-application viewing. Marketing must describe these limits accurately.

## Release priorities and acceptance criteria

1. **Reliable everyday files.** Representative agency DOCX/PPTX/XLSX/PDF
   fixtures open without UI blocking; warm previews reuse the cache; originals
   keep identical hashes. Corrupt/protected files give useful errors. Include
   long workbooks, merged cells, charts, unusual fonts and large presentations.
2. **Campaign export sets.** Save a client/campaign profile and produce named
   image/video/document deliverables with a single preset. Show exact outputs,
   preserve source files by default, and retry only failed outputs. The first
   built-in sets and retry receipts are implemented; custom set editing,
   visual crop positioning, video sizing controls and campaign milestones remain.
3. **Local review and handoff.** Package files and a review index with stable
   version IDs/checksums. Export/import review comments locally; approvals must
   be attributable and show which version was reviewed. No public uploads.
4. **Developer and IT readiness.** Document the existing local API with working
   examples, keep it bound to loopback by default, and provide configuration
   backup, diagnostics, upgrade rollback and a clean-install test.
5. **Commercial readiness.** Test the supported operating systems and display
   scales, audit model/runtime licenses, reconcile installer contents with the
   UI, document minimum hardware and support limits, and run a complete release
   regression. A fresh install must require no developer tools for included
   workflows. Do not label this complete until those gates pass.

## Optional online work, after the local workflow is solid

Potential free connections: agency-owned file server/WebDAV, version-control
repositories, or services with a verified free tier for file sharing and review
notifications. Sharing is explicit, account credentials stay out of diagnostic
exports, and network errors cannot lose local work. Free plans and API limits
must be verified when a connector is implemented; they are not assumed here.

Paid hosted AI voices, paid scheduling/publishing APIs, mandatory subscriptions
and dependency on hosted approval services are out of scope for now. The
existing optional publishing/storage adapters require a separate cost and
permissions audit before they can be promoted as free agency features.
