import json
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber
import pymupdf as fitz
import pytesseract
from langchain_core.documents import Document
from PIL import Image

from packages.exceptions import ParsingError


class ComplexPDFParser:
    """Parse a complex PDF containing selectable text, scanned pages, tables, and embedded
    images into LangChain Documents suitable for RAG. Ported from the V1 prototype
    (src/parsing.py::ComplexPDFParser) with no behavior change — see
    specs/020-async-ingestion-pipeline/plan.md."""

    def __init__(
        self,
        pdf_path: str,
        output_dir: str,
        tesseract_path: str | None = None,
        render_scale: float = 2.0,
    ) -> None:
        self.pdf_path = Path(pdf_path)
        self.output_dir = Path(output_dir)
        self.image_dir = self.output_dir / "extracted_images"
        self.page_image_dir = self.output_dir / "page_images"
        self.render_scale = render_scale

        self.page_records: list[dict[str, Any]] = []
        self.image_records: list[dict[str, Any]] = []
        self.table_records: list[dict[str, Any]] = []
        self.langchain_docs: list[Document] = []

        try:
            self._validate_pdf()
            self._create_output_directories()
            self._configure_tesseract(tesseract_path)
        except Exception as exc:
            raise ParsingError(
                f"Failed to initialize the PDF parser for {self.pdf_path}", exc
            ) from exc

    # ============================================================
    # Setup
    # ============================================================

    def _validate_pdf(self) -> None:
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {self.pdf_path}")

    def _create_output_directories(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.page_image_dir.mkdir(parents=True, exist_ok=True)

    def _configure_tesseract(self, tesseract_path: str | None) -> None:
        if tesseract_path:
            path = Path(tesseract_path)
            if not path.exists():
                raise FileNotFoundError(f"Tesseract executable not found at: {path}")
            pytesseract.pytesseract.tesseract_cmd = str(path)

    # ============================================================
    # OCR
    # ============================================================

    def run_ocr_on_image(self, image_path: str | Path) -> str:
        """OCR failures degrade gracefully — a marker string is embedded in the returned
        text instead of raising, so one bad image never fails the whole parse."""
        try:
            with Image.open(image_path) as image:
                text = pytesseract.image_to_string(image)
            return text.strip()
        except Exception as exc:
            return f"[OCR_SKIPPED_OR_FAILED: {exc}]"

    # ============================================================
    # PyMuPDF: Text + Images + Full-page OCR
    # ============================================================

    def extract_text_and_images(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        page_records: list[dict[str, Any]] = []
        image_records: list[dict[str, Any]] = []

        pdf = fitz.open(str(self.pdf_path))

        try:
            for page_index in range(len(pdf)):
                page = pdf[page_index]
                page_number = page_index + 1

                images = page.get_images(full=True)
                selectable_text = page.get_text("text").strip()

                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(self.render_scale, self.render_scale)
                )

                page_image_path = self.page_image_dir / f"page_{page_number:03d}.png"
                pixmap.save(str(page_image_path))

                page_ocr_text = self.run_ocr_on_image(page_image_path)

                page_records.append(
                    {
                        "page_number": page_number,
                        "text": selectable_text,
                        "ocr_text": page_ocr_text,
                        "image_count": len(images),
                        "width": page.rect.width,
                        "height": page.rect.height,
                        "page_image_path": str(page_image_path),
                    }
                )

                for image_index, image_info in enumerate(images, start=1):
                    xref = image_info[0]
                    base_image = pdf.extract_image(xref)

                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]

                    image_path = (
                        self.image_dir / f"page_{page_number:03d}_image_{image_index}.{image_ext}"
                    )

                    with open(image_path, "wb") as file:
                        file.write(image_bytes)

                    image_ocr_text = self.run_ocr_on_image(image_path)

                    image_records.append(
                        {
                            "page_number": page_number,
                            "image_index": image_index,
                            "image_path": str(image_path),
                            "image_ext": image_ext,
                            "image_ocr_text": image_ocr_text,
                        }
                    )
        finally:
            pdf.close()

        self.page_records = page_records
        self.image_records = image_records

        return page_records, image_records

    # ============================================================
    # pdfplumber: Tables
    # ============================================================

    def extract_tables(self) -> list[dict[str, Any]]:
        table_records: list[dict[str, Any]] = []

        with pdfplumber.open(str(self.pdf_path)) as pdf:
            for page_index, page in enumerate(pdf.pages):
                page_number = page_index + 1

                try:
                    tables = page.extract_tables() or []
                except Exception:
                    tables = []

                for table_index, table in enumerate(tables, start=1):
                    if not table:
                        continue

                    cleaned_table = []
                    for row in table:
                        cleaned_row = [
                            cell.strip() if isinstance(cell, str) else cell for cell in row
                        ]
                        cleaned_table.append(cleaned_row)

                    if not cleaned_table:
                        continue

                    try:
                        dataframe = pd.DataFrame(cleaned_table[1:], columns=cleaned_table[0])
                    except Exception:
                        dataframe = pd.DataFrame(cleaned_table)

                    table_records.append(
                        {
                            "page_number": page_number,
                            "table_index": table_index,
                            "raw_table": cleaned_table,
                            "markdown": dataframe.to_markdown(index=False),
                            "csv": dataframe.to_csv(index=False),
                        }
                    )

        self.table_records = table_records
        return table_records

    # ============================================================
    # LangChain Documents
    # ============================================================

    def create_langchain_documents(self) -> list[Document]:
        documents: list[Document] = []

        for page in self.page_records:
            page_number = page["page_number"]
            combined_text = f"""
PAGE {page_number}

SELECTABLE TEXT:
{page["text"]}

OCR TEXT:
{page["ocr_text"]}
""".strip()

            documents.append(
                Document(
                    page_content=combined_text,
                    metadata={
                        "source": str(self.pdf_path),
                        "page_number": page_number,
                        "content_type": "page_text_plus_ocr",
                        "image_count": page["image_count"],
                        "page_image_path": page["page_image_path"],
                    },
                )
            )

        for table in self.table_records:
            page_number = table["page_number"]
            table_text = f"""
TABLE FOUND ON PAGE {page_number}
TABLE INDEX: {table["table_index"]}

TABLE MARKDOWN:
{table["markdown"]}
""".strip()

            documents.append(
                Document(
                    page_content=table_text,
                    metadata={
                        "source": str(self.pdf_path),
                        "page_number": page_number,
                        "content_type": "table",
                        "table_index": table["table_index"],
                    },
                )
            )

        for image in self.image_records:
            page_number = image["page_number"]
            image_text = f"""
IMAGE FOUND ON PAGE {page_number}
IMAGE INDEX: {image["image_index"]}
IMAGE PATH: {image["image_path"]}

IMAGE OCR TEXT:
{image["image_ocr_text"]}
""".strip()

            documents.append(
                Document(
                    page_content=image_text,
                    metadata={
                        "source": str(self.pdf_path),
                        "page_number": page_number,
                        "content_type": "image",
                        "image_index": image["image_index"],
                        "image_path": image["image_path"],
                        "image_ext": image["image_ext"],
                    },
                )
            )

        self.langchain_docs = documents
        return documents

    # ============================================================
    # Save Outputs (optional debug dump — off by default; workers don't rely on this)
    # ============================================================

    @staticmethod
    def _save_json(path: Path, data: Any) -> None:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False, default=str)

    def save_outputs(self) -> None:
        self._save_json(self.output_dir / "page_records.json", self.page_records)
        self._save_json(self.output_dir / "image_records.json", self.image_records)
        self._save_json(self.output_dir / "table_records.json", self.table_records)

    # ============================================================
    # Main Pipeline
    # ============================================================

    def parse(self, save_output: bool = False) -> dict[str, Any]:
        """Returns {"pages": [...], "images": [...], "tables": [...],
        "documents": [LangChain Document, ...], "output_dir": "..."}."""
        try:
            self.extract_text_and_images()
            self.extract_tables()
            self.create_langchain_documents()

            if save_output:
                self.save_outputs()

            return {
                "pages": self.page_records,
                "images": self.image_records,
                "tables": self.table_records,
                "documents": self.langchain_docs,
                "output_dir": str(self.output_dir),
            }
        except ParsingError:
            raise
        except Exception as exc:
            raise ParsingError(f"Failed to parse PDF: {self.pdf_path}", exc) from exc
