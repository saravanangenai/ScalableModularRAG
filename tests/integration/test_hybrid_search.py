"""Requires real Postgres, MinIO, Keycloak, Qdrant, and Memurai, plus a running Celery
worker and a real OPENAI_API_KEY — same stack as test_upload_and_ingest.py.

Demonstrates the sparse leg specs/040-hybrid-retrieval-reranking added matters, not just
that the pipeline runs: tests/fixtures/sample.pdf's page 9 contains an exact, rare
alphanumeric string ("BLR-MSA-2026-019", a synthetic Contract ID) that dense embeddings
under-weight (it's semantically meaningless — no paraphrase relates to it) but BM25 matches
directly on the literal token. This is exactly the class of query
specs/architecture/04-retrieval-design.md §1 names as dense-only's weak spot.
"""

from tests.integration.test_upload_and_ingest import (
    FIXTURE_PDF,
    _auth,
    _create_workspace,
    _poll_job_until_terminal,
)

LEXICAL_QUERY = "BLR-MSA-2026-019"


async def test_lexical_exact_match_query_surfaces_the_correct_chunk(api_client, user1_token):
    workspace_id = await _create_workspace(api_client, user1_token)

    upload_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("sample.pdf", FIXTURE_PDF.read_bytes(), "application/pdf")},
        headers=_auth(user1_token),
    )
    assert upload_response.status_code == 202
    job_id = upload_response.json()["job_id"]

    job = await _poll_job_until_terminal(api_client, user1_token, workspace_id, job_id)
    assert job["status"] == "ready", job.get("failure_reason")

    response = await api_client.post(
        f"/workspaces/{workspace_id}/search",
        json={"query": LEXICAL_QUERY, "k": 5},
        headers=_auth(user1_token),
    )
    assert response.status_code == 200

    results = response.json()["results"]
    assert len(results) > 0
    assert any(LEXICAL_QUERY in (result["text"] or "") for result in results), (
        f"expected a chunk containing {LEXICAL_QUERY!r} in the top {len(results)} results, "
        f"got: {[r['text'] for r in results]}"
    )
