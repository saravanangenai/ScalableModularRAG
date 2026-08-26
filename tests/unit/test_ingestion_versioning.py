from packages.ingestion.versioning import content_hash, is_unchanged


def test_content_hash_is_deterministic_sha256():
    assert content_hash(b"hello") == content_hash(b"hello")
    assert content_hash(b"hello") != content_hash(b"world")
    assert len(content_hash(b"hello")) == 64


def test_is_unchanged_true_when_hash_matches_current():
    assert is_unchanged("abc123", "abc123") is True


def test_is_unchanged_false_when_hash_differs():
    assert is_unchanged("abc123", "def456") is False


def test_is_unchanged_false_when_no_current_version():
    assert is_unchanged("abc123", None) is False
