"""Exercise real bundled engines without starting a GUI or downloading anything."""
from pathlib import Path
import json
import tempfile
import traceback


def run(destination: Path) -> int:
    checks = []
    with tempfile.TemporaryDirectory(prefix="shadow-studio-smoke-") as td:
        root = Path(td)
        def check(name, action):
            try:
                action()
                checks.append({"name": name, "passed": True})
            except Exception as exc:
                checks.append({"name": name, "passed": False, "error": str(exc), "traceback": traceback.format_exc()})

        def office():
            from docx import Document
            from pptx import Presentation
            from openpyxl import Workbook
            from doc_converter import convert_document
            from pypdf import PdfReader
            doc = Document()
            doc.add_paragraph("Agency document smoke test")
            doc.save(root / "proposal.docx")
            deck = Presentation()
            deck.slides.add_slide(deck.slide_layouts[1]).shapes.title.text = "Agency pitch"
            deck.save(root / "pitch.pptx")
            book = Workbook()
            book.active.append(["Budget", 500])
            book.save(root / "budget.xlsx")
            book.close()
            for source in (root / "proposal.docx", root / "pitch.pptx", root / "budget.xlsx"):
                result = convert_document(source, root / "converted", "PDF")
                if result.status != "Completed":
                    raise RuntimeError(result.error)
                if len(PdfReader(result.output_path).pages) < 1:
                    raise RuntimeError("Office export has no pages")

        def pdf():
            from pdf_tools import render_pdf_page, process_pdf
            from pypdf import PdfWriter
            source = root / "preview.pdf"
            with PdfWriter() as writer:
                writer.add_blank_page(width=300, height=400)
                writer.write(source)
            image, count = render_pdf_page(source)
            image.close()
            if count != 1:
                raise RuntimeError("Wrong PDF page count")
            process_pdf([source], root / "pages.zip", "images")

        def speech():
            from speech_engine import synthesize_speech, transcribe_media
            audio = synthesize_speech("Hello. This is the agency studio. We create marketing campaigns.", root / "voice.wav")
            result = transcribe_media(audio, root, "SRT")
            if result.status != "Completed":
                raise RuntimeError(result.error)
            if "agency" not in result.output_path.read_text(encoding="utf-8").lower():
                raise RuntimeError("Speech round trip did not recover the expected text")

        def audio():
            import wave
            from audio_tools import process_audio
            source = root / "silent.wav"
            with wave.open(str(source), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"\x00\x00" * 32000)
            process_audio(source, root / "delivery.mp3", "MP3", denoise=True)

        check("Office DOCX/PPTX/XLSX to PDF", office)
        check("PDF rendering and page image export", pdf)
        check("English speech synthesis and transcription", speech)
        check("Audio normalization, denoising, and MP3 export", audio)
    destination.parent.mkdir(parents=True, exist_ok=True)
    passed = all(check["passed"] for check in checks)
    destination.write_text(json.dumps({"passed": passed, "checks": checks}, indent=2), encoding="utf-8")
    return 0 if passed else 1
