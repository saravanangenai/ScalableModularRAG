import pytest

from eval.dataset import EvalCase, load_dataset
from packages.exceptions import EvalError


def test_load_dataset_parses_valid_rows(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"id": "Q-001", "question": "What is the refund window?", '
        '"expected_filename": "sample.pdf", "expected_page_number": 5, '
        '"expected_content_type": "table", "expected_table_index": 1, '
        '"expected_image_index": null}\n',
        encoding="utf-8",
    )

    cases = load_dataset(path)

    assert cases == [
        EvalCase(
            id="Q-001",
            question="What is the refund window?",
            expected_filename="sample.pdf",
            expected_page_number=5,
            expected_content_type="table",
            expected_table_index=1,
            expected_image_index=None,
        )
    ]


def test_load_dataset_defaults_optional_fields_to_none(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"id": "Q-002", "question": "q", "expected_filename": "sample.pdf", '
        '"expected_page_number": 4, "expected_content_type": "page_text_plus_ocr"}\n',
        encoding="utf-8",
    )

    cases = load_dataset(path)

    assert cases[0].expected_table_index is None
    assert cases[0].expected_image_index is None


def test_load_dataset_skips_blank_lines(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"id": "Q-001", "question": "q", "expected_filename": "sample.pdf", '
        '"expected_page_number": 1, "expected_content_type": "table"}\n'
        "\n"
        '{"id": "Q-002", "question": "q2", "expected_filename": "sample.pdf", '
        '"expected_page_number": 2, "expected_content_type": "table"}\n',
        encoding="utf-8",
    )

    cases = load_dataset(path)

    assert [c.id for c in cases] == ["Q-001", "Q-002"]


def test_load_dataset_raises_on_missing_required_field(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text('{"id": "Q-001", "question": "q"}\n', encoding="utf-8")

    with pytest.raises(EvalError, match="missing required field"):
        load_dataset(path)


def test_load_dataset_raises_on_invalid_json(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("not json\n", encoding="utf-8")

    with pytest.raises(EvalError, match="invalid JSON"):
        load_dataset(path)


def test_load_dataset_returns_empty_list_for_empty_file(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("", encoding="utf-8")

    assert load_dataset(path) == []


def test_load_dataset_raises_for_missing_file():
    with pytest.raises(EvalError):
        load_dataset("/no/such/file.jsonl")
