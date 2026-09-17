import json
from dataclasses import dataclass
from pathlib import Path

from packages.exceptions import EvalError

_REQUIRED_FIELDS = {"id", "question", "expected_filename", "expected_page_number", "expected_content_type"}


@dataclass
class EvalCase:
    id: str
    question: str
    expected_filename: str
    expected_page_number: int
    expected_content_type: str
    expected_table_index: int | None = None
    expected_image_index: int | None = None


def load_dataset(path: str | Path) -> list[EvalCase]:
    """Parses a golden-dataset JSONL file (one case per line) into EvalCase objects —
    specs/060-retrieval-evaluation. Raises EvalError with the offending line number on any
    malformed row, rather than silently skipping it."""
    cases: list[EvalCase] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvalError(f"failed to read dataset file {path!r}", original_exception=exc) from exc

    for line_number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalError(
                f"invalid JSON on line {line_number} of {path!r}", original_exception=exc
            ) from exc

        missing = _REQUIRED_FIELDS - row.keys()
        if missing:
            raise EvalError(
                f"line {line_number} of {path!r} is missing required field(s): {sorted(missing)}"
            )

        cases.append(
            EvalCase(
                id=row["id"],
                question=row["question"],
                expected_filename=row["expected_filename"],
                expected_page_number=row["expected_page_number"],
                expected_content_type=row["expected_content_type"],
                expected_table_index=row.get("expected_table_index"),
                expected_image_index=row.get("expected_image_index"),
            )
        )

    return cases
