import inspect
import uuid

from qdrant_client import models

from packages.retrieval.filters import build_workspace_filter


def test_build_workspace_filter_scopes_to_workspace_and_current_version():
    workspace_id = uuid.uuid4()

    result = build_workspace_filter(workspace_id)

    assert result == models.Filter(
        must=[
            models.FieldCondition(
                key="workspace_id", match=models.MatchValue(value=str(workspace_id))
            ),
            models.FieldCondition(
                key="is_current_version", match=models.MatchValue(value=True)
            ),
        ]
    )


def test_build_workspace_filter_has_no_other_input():
    """The whole point of the mandatory filter is that nothing else can parameterize it —
    assert the function's signature has exactly one parameter."""
    parameters = inspect.signature(build_workspace_filter).parameters
    assert list(parameters) == ["workspace_id"]
