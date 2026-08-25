import uuid

from packages.storage.keys import document_key, image_key


def test_document_key_shape():
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    document_id = uuid.uuid4()
    content_hash = "deadbeef"

    key = document_key(tenant_id, workspace_id, document_id, content_hash)

    assert key == f"{tenant_id}/{workspace_id}/{document_id}/deadbeef.pdf"


def test_document_key_is_deterministic_for_same_content_hash():
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    document_id = uuid.uuid4()

    key_a = document_key(tenant_id, workspace_id, document_id, "samehash")
    key_b = document_key(tenant_id, workspace_id, document_id, "samehash")

    assert key_a == key_b


def test_image_key_shape():
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    document_id = uuid.uuid4()
    document_version_id = uuid.uuid4()

    key = image_key(tenant_id, workspace_id, document_id, document_version_id, 3)

    assert key == (
        f"{tenant_id}/{workspace_id}/{document_id}/{document_version_id}/images/3.png"
    )
