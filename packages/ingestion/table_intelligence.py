import re
import warnings

import pandas as pd
from langchain_openai import ChatOpenAI

from packages.observability import get_logger

logger = get_logger(__name__)

_CURRENCY_PATTERN = re.compile(r"^[$₹€£]\s?-?[\d,]+\.?\d*$|^-?[\d,]+\.?\d*\s?%$")

_SUMMARY_PROMPT_TEMPLATE = (
    "Describe this table for a document search index in 2-4 sentences. Cover: what the "
    "table contains (topic/domain), what the columns represent, and any notable ranges or "
    "patterns in the data. Be concise and factual.\n\nTABLE (markdown):\n{markdown}"
)


def infer_column_types(dataframe: pd.DataFrame) -> list[dict]:
    """Heuristic (pandas-based, no LLM) column type inference — specs/051-table-intelligence
    deliberately avoids a second LLM call per table (one already runs for the summary).
    Returns [{"name": ..., "type": "string" | "number" | "date" | "currency"}, ...].
    """
    columns = []
    for name in dataframe.columns:
        series = dataframe[name].astype(str).str.strip()
        non_null = series[(series != "") & (series.str.lower() != "none") & (series.str.lower() != "nan")]

        if non_null.empty:
            columns.append({"name": str(name), "type": "string"})
            continue

        if non_null.map(lambda value: bool(_CURRENCY_PATTERN.match(value))).all():
            columns.append({"name": str(name), "type": "currency"})
            continue

        try:
            pd.to_numeric(non_null.str.replace(",", ""))
            columns.append({"name": str(name), "type": "number"})
            continue
        except (ValueError, TypeError):
            pass

        try:
            with warnings.catch_warnings():
                # Plain non-date strings (e.g. "Arka Finance") make to_datetime fall back to
                # a slow per-element dateutil parse before it raises — that fallback still
                # correctly fails for non-dates, it's just noisy; the warning isn't actionable
                # here since this is a best-effort heuristic classification, not exact parsing.
                warnings.simplefilter("ignore", UserWarning)
                pd.to_datetime(non_null, errors="raise")
            columns.append({"name": str(name), "type": "date"})
            continue
        except (ValueError, TypeError):
            pass

        columns.append({"name": str(name), "type": "string"})

    return columns


def chunk_table_by_rows(
    dataframe: pd.DataFrame, threshold: int, group_size: int
) -> list[pd.DataFrame]:
    """Splits a table into row-groups once it exceeds `threshold` rows, `group_size` rows
    per group (last group may be smaller) — specs/051-table-intelligence, replacing the
    single-oversized-chunk behavior specs/architecture/05-multimodal-strategy.md §2 names.
    Each returned DataFrame keeps the same columns, so the header is implicitly preserved
    in every group.
    """
    if len(dataframe) <= threshold:
        return [dataframe]

    return [
        dataframe.iloc[start : start + group_size]
        for start in range(0, len(dataframe), group_size)
    ]


def summarize_table(chat_model: ChatOpenAI, markdown: str) -> str | None:
    """One LLM call per table. Never raises — degrades to None (caller falls back to raw
    markdown as embedded text) on any failure, same contract as
    packages/ingestion/vision.py::caption_image."""
    try:
        prompt = _SUMMARY_PROMPT_TEMPLATE.format(markdown=markdown)
        response = chat_model.invoke(prompt)
        summary = str(response.content).strip()
        return summary or None
    except Exception as exc:
        logger.warning("table_summary_failed", error=str(exc))
        return None
