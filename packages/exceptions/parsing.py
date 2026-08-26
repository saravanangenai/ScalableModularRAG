from packages.exceptions.base import DocumentPortalException


class ParsingError(DocumentPortalException):
    """Raised at packages/parsing's public function boundaries for any underlying
    PDF-parsing/OCR/table-extraction failure."""
