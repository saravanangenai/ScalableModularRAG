import json
import logging

from packages.observability import configure_logging, get_logger


def test_configure_logging_produces_structured_json_output(capsys):
    configure_logging(level=logging.INFO)
    logger = get_logger("test")

    logger.info("sample_event", job_id="abc-123", stage="parsing")

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])

    assert payload["event"] == "sample_event"
    assert payload["job_id"] == "abc-123"
    assert payload["stage"] == "parsing"
    assert payload["level"] == "info"


def test_configure_logging_filters_below_configured_level(capsys):
    configure_logging(level=logging.WARNING)
    logger = get_logger("test")

    logger.info("should_not_appear")
    logger.warning("should_appear")

    captured = capsys.readouterr()
    events = [json.loads(line)["event"] for line in captured.out.strip().splitlines() if line]

    assert "should_not_appear" not in events
    assert "should_appear" in events
