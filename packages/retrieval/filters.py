import uuid

from qdrant_client import models


def build_workspace_filter(workspace_id: uuid.UUID) -> models.Filter:
    """The mandatory, server-constructed Qdrant filter every retrieval call applies —
    per specs/architecture/06-security-model.md §4 and
    specs/030-workspace-rbac-filtering/plan.md. workspace_id is the only input; there is no
    way to pass any other field into this filter, so nothing calling it can smuggle a
    client-supplied override in. Also restricts to the current document version, so a
    superseded version's chunks (packages/ingestion/pipeline.py flips is_current_version to
    false on supersession) never surface.
    """
    return models.Filter(
        must=[
            models.FieldCondition(
                key="workspace_id", match=models.MatchValue(value=str(workspace_id))
            ),
            models.FieldCondition(
                key="is_current_version", match=models.MatchValue(value=True)
            ),
        ]
    )
