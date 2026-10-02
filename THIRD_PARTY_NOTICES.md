# Agency Studio third-party notices

Bundled third-party components and model assets retain their own licenses.
The application EULA does not replace their license terms.

- LibreOffice: MPL 2.0 and component licenses; `vendor/libreoffice/license.txt`
  and `LICENSE.html` accompany the runtime. Source: https://www.libreoffice.org/.
- FFmpeg: GPL build and notices in `bin/LICENSE-ffmpeg-GPLv3.txt`.
  Source: https://ffmpeg.org/.
- Ghostscript: GNU AGPLv3; runtime notices and COPYING are under
  `vendor/ghostscript/doc`. Corresponding source for the bundled Windows release:
  https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/tag/gs10080.
- Piper: GPLv3; source https://github.com/OHF-Voice/piper1-gpl.
  Voice model cards are staged under `vendor/models/licenses` or `voices`.
  Each voice retains its model/dataset license.
- faster-whisper and CTranslate2: MIT; sources
  https://github.com/SYSTRAN/faster-whisper and https://github.com/OpenNMT/CTranslate2.
  Whisper model source: https://github.com/openai/whisper.
- RapidOCR: Apache 2.0; source https://github.com/RapidAI/RapidOCR.
  Recognition model metadata is retained with the installed package.
- sherpa-onnx: Apache 2.0 and upstream model licenses; source
  https://github.com/k2-fsa/sherpa-onnx.
- RNNoise models: retain the upstream model notices;
  https://github.com/GregorR/rnnoise-models.
- OPUS-MT translation models: retain their individual model cards and licenses;
  https://huggingface.co/Helsinki-NLP and the catalog's linked model repositories.
- PDFium, pyHanko, pypdf, pdfplumber, Pillow, python-docx, python-pptx,
  openpyxl, fontTools, ONNX Runtime, and cloud SDKs retain their upstream licenses.
  Installed package metadata and bundled runtime resources contain their notices.

Model download provenance is recorded by `setup_model_notices.py` in
`vendor/models/licenses/catalog.json`. Optional downloads use the catalog's
published source URLs and retain downloaded notices alongside their assets.
