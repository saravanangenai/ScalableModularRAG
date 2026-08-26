import tempfile
from pathlib import Path

from packages.parsing import ComplexPDFParser

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "sample.pdf"


def test_parse_produces_non_empty_pages_and_documents():
    with tempfile.TemporaryDirectory() as tmp_dir:
        parser = ComplexPDFParser(pdf_path=str(FIXTURE_PDF), output_dir=tmp_dir)
        result = parser.parse(save_output=False)

        assert len(result["pages"]) > 0
        assert len(result["documents"]) > 0
        assert all(doc.metadata["content_type"] for doc in result["documents"])


def test_parse_extracts_at_least_one_table_or_image():
    with tempfile.TemporaryDirectory() as tmp_dir:
        parser = ComplexPDFParser(pdf_path=str(FIXTURE_PDF), output_dir=tmp_dir)
        result = parser.parse(save_output=False)

        assert len(result["tables"]) > 0 or len(result["images"]) > 0


def test_page_documents_carry_selectable_and_ocr_text():
    with tempfile.TemporaryDirectory() as tmp_dir:
        parser = ComplexPDFParser(pdf_path=str(FIXTURE_PDF), output_dir=tmp_dir)
        result = parser.parse(save_output=False)

        page_documents = [
            doc for doc in result["documents"] if doc.metadata["content_type"] == "page_text_plus_ocr"
        ]
        assert len(page_documents) == len(result["pages"])
        assert "SELECTABLE TEXT:" in page_documents[0].page_content
        assert "OCR TEXT:" in page_documents[0].page_content


def test_save_output_writes_json_files_when_enabled():
    with tempfile.TemporaryDirectory() as tmp_dir:
        parser = ComplexPDFParser(pdf_path=str(FIXTURE_PDF), output_dir=tmp_dir)
        parser.parse(save_output=True)

        assert (Path(tmp_dir) / "page_records.json").exists()
        assert (Path(tmp_dir) / "table_records.json").exists()
        assert (Path(tmp_dir) / "image_records.json").exists()
