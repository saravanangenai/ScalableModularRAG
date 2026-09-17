from unittest.mock import patch

from packages.observability.sentry import configure_sentry


def test_configure_sentry_noops_when_dsn_is_none():
    with patch("packages.observability.sentry.sentry_sdk.init") as mock_init:
        configure_sentry(None, "local")

    mock_init.assert_not_called()


def test_configure_sentry_initializes_when_dsn_is_set():
    with patch("packages.observability.sentry.sentry_sdk.init") as mock_init:
        configure_sentry("https://example@o0.ingest.sentry.io/0", "production")

    mock_init.assert_called_once()
    _, kwargs = mock_init.call_args
    assert kwargs["dsn"] == "https://example@o0.ingest.sentry.io/0"
    assert kwargs["environment"] == "production"
