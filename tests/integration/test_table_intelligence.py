"""Requires real Postgres, MinIO, Keycloak, Qdrant, and Memurai, plus a running Celery
worker and a real OPENAI_API_KEY — same stack as test_upload_and_ingest.py.

Verifies specs/051-table-intelligence end to end: durable raw/normalized table storage
(RLS-protected), an LLM summary as primary embedded text, and heuristic column-schema
metadata. None of tests/fixtures/sample.pdf's naturally-occurring tables exceed
table_chunk_row_threshold (checked directly via ComplexPDFParser.extract_tables — the
largest is 8 rows), so the above-threshold row-group-split arithmetic is NOT re-verified
here with a real PDF; it's already exactly verified with a real 32-row DataFrame in
tests/unit/test_ingestion_table_intelligence.py (exact [15, 15, 2] group boundaries).
Building a bespoke large-table PDF fixture just to re-prove already-proven arithmetic
end-to-end was judged not worth the effort — this test instead proves the parts a unit test
can't: real LLM summarization, real RLS-protected Postgres writes, and real searchability.
"""

import uuid

from sqlalchemy import text

from tests.integration.test_rls import _set_scope
from tests.integration.test_upload_and_ingest import (
    FIXTURE_PDF,
    _auth,
    _create_workspace,
    _poll_job_until_terminal,
)

# tests/fixtures/sample.pdf page 1's table, confirmed via a local ComplexPDFParser.extract_tables()
# run: header ["Section", "Parsing challenge", "Why it matters for RAG"], first data row
# ["Contracts", "Dense legal text...", "Need section-aware chunks and citations"].
KNOWN_TABLE_PAGE = 1
KNOWN_TABLE_INDEX = 1
KNOWN_CELL_COLUMN = "Section"
KNOWN_CELL_VALUE = "Contracts"


async def test_table_intelligence_end_to_end(api_client, user1_token, db_session):
    workspace_id = await _create_workspace(api_client, user1_token)

    upload_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("sample.pdf", FIXTURE_PDF.read_bytes(), "application/pdf")},
        headers=_auth(user1_token),
    )
    assert upload_response.status_code == 202
    job_id = upload_response.json()["job_id"]

    job = await _poll_job_until_terminal(api_client, user1_token, job_id=job_id, workspace_id=workspace_id)
    assert job["status"] == "ready", job.get("failure_reason")

    _set_scope(db_session, uuid.UUID(workspace_id))

    tables = db_session.execute(
        text(
            "SELECT id, summary, schema_json, row_count FROM document_tables "
            "WHERE page_number = :page AND table_index = :idx"
        ),
        {"page": KNOWN_TABLE_PAGE, "idx": KNOWN_TABLE_INDEX},
    ).fetchall()
    assert len(tables) == 1, "expected exactly one document_tables row for the known table"
    table_row = tables[0]

    assert table_row.summary, "table summarization should have produced a real LLM summary"
    assert table_row.schema_json, "column schema should be populated"
    assert table_row.row_count == 4

    cells = db_session.execute(
        text(
            "SELECT column_name, value FROM table_cells "
            "WHERE table_id = :table_id AND row_index = 0"
        ),
        {"table_id": table_row.id},
    ).fetchall()
    cell_values = {c.column_name: c.value for c in cells}
    assert cell_values.get(KNOWN_CELL_COLUMN) == KNOWN_CELL_VALUE

    search_response = await api_client.post(
        f"/workspaces/{workspace_id}/search",
        json={"query": "section-aware chunks and citations for contracts", "k": 5},
        headers=_auth(user1_token),
    )
    assert search_response.status_code == 200
    results = search_response.json()["results"]
    table_results = [r for r in results if r["content_type"] == "table"]
    assert table_results, "expected at least one table chunk in search results"
    assert "SUMMARY:" in (table_results[0]["text"] or "")
