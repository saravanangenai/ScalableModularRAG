from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from packages.ingestion.table_intelligence import (
    chunk_table_by_rows,
    infer_column_types,
    summarize_table,
)


def test_infer_column_types_detects_numbers():
    df = pd.DataFrame({"quantity": ["1", "2", "1,500", "42"]})
    result = infer_column_types(df)
    assert result == [{"name": "quantity", "type": "number"}]


def test_infer_column_types_detects_currency():
    df = pd.DataFrame({"price": ["$100", "$200.50", "$1,000.00"]})
    result = infer_column_types(df)
    assert result == [{"name": "price", "type": "currency"}]


def test_infer_column_types_detects_dates():
    df = pd.DataFrame({"effective_date": ["2026-01-01", "2026-02-15", "2026-03-20"]})
    result = infer_column_types(df)
    assert result == [{"name": "effective_date", "type": "date"}]


def test_infer_column_types_falls_back_to_string():
    df = pd.DataFrame({"client": ["Arka Finance", "BlueLeaf Retail", "CityRide Mobility"]})
    result = infer_column_types(df)
    assert result == [{"name": "client", "type": "string"}]


def test_infer_column_types_handles_multiple_columns_independently():
    df = pd.DataFrame(
        {
            "client": ["Arka Finance", "BlueLeaf Retail"],
            "amount": ["$500", "$750"],
            "count": ["3", "5"],
        }
    )
    result = infer_column_types(df)
    assert {c["name"]: c["type"] for c in result} == {
        "client": "string",
        "amount": "currency",
        "count": "number",
    }


def test_chunk_table_by_rows_stays_one_chunk_at_or_below_threshold():
    df = pd.DataFrame({"col": range(20)})
    chunks = chunk_table_by_rows(df, threshold=20, group_size=15)
    assert len(chunks) == 1
    assert len(chunks[0]) == 20


def test_chunk_table_by_rows_splits_above_threshold():
    df = pd.DataFrame({"col": range(32)})
    chunks = chunk_table_by_rows(df, threshold=20, group_size=15)
    assert len(chunks) == 3
    assert [len(c) for c in chunks] == [15, 15, 2]
    for chunk in chunks:
        assert list(chunk.columns) == ["col"]


def test_summarize_table_returns_the_llm_response():
    chat_model = MagicMock()
    chat_model.invoke.return_value = SimpleNamespace(content="A pricing table by region.")

    result = summarize_table(chat_model, "| Plan | Price |\n|---|---|\n| A | $10 |")

    assert result == "A pricing table by region."
    chat_model.invoke.assert_called_once()


def test_summarize_table_returns_none_on_failure():
    chat_model = MagicMock()
    chat_model.invoke.side_effect = RuntimeError("rate limited")

    result = summarize_table(chat_model, "| Plan | Price |")

    assert result is None


def test_summarize_table_returns_none_for_blank_response():
    chat_model = MagicMock()
    chat_model.invoke.return_value = SimpleNamespace(content="   ")

    result = summarize_table(chat_model, "| Plan | Price |")

    assert result is None
