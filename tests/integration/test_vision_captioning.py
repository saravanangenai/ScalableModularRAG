"""Requires real Postgres, MinIO, Keycloak, Qdrant, and Memurai, plus a running Celery
worker and a real OPENAI_API_KEY — same stack as test_upload_and_ingest.py.

Demonstrates specs/050-vision-captioning matters, not just that it runs: tests/fixtures/
sample.pdf page 24 ("Appendix I: Profile Image for Multimodal Parsing") is a portrait photo
with essentially no visible/OCR-able text — confirmed via a live caption:
"...no discernible numbers or other text." OCR-only retrieval (V1's limitation, per
specs/architecture/05-multimodal-strategy.md §1) could never match a query describing what
this image depicts, since there's no text to match against. Vision captioning gives it a
real chance.
"""

from tests.integration.test_upload_and_ingest import (
    FIXTURE_PDF,
    _auth,
    _create_workspace,
    _poll_job_until_terminal,
)

SEMANTIC_QUERY = "a professional headshot photo of a person for a team page or LinkedIn profile"
PORTRAIT_IMAGE_PAGE = 24


async def test_semantic_query_surfaces_a_text_free_image_via_its_vision_caption(
    api_client, user1_token
):
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
        json={"query": SEMANTIC_QUERY, "k": 5},
        headers=_auth(user1_token),
    )
    assert response.status_code == 200

    results = response.json()["results"]
    assert len(results) > 0
    assert any(result["page_number"] == PORTRAIT_IMAGE_PAGE for result in results), (
        f"expected the page-{PORTRAIT_IMAGE_PAGE} portrait image in the top "
        f"{len(results)} results for a query describing what it depicts, got pages: "
        f"{[r['page_number'] for r in results]}"
    )
    matched = next(r for r in results if r["page_number"] == PORTRAIT_IMAGE_PAGE)
    assert matched["content_type"] == "image"
    assert "VISION CAPTION" in (matched["text"] or "")
