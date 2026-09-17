import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage

from packages.ingestion.vision import caption_image


def test_caption_image_sends_a_multimodal_message_and_returns_the_caption(tmp_path):
    image_path = tmp_path / "chart.png"
    image_bytes = b"not-a-real-png-but-bytes-are-enough-for-this-test"
    image_path.write_bytes(image_bytes)

    chat_model = MagicMock()
    chat_model.invoke.return_value = SimpleNamespace(content="A bar chart showing sales.")

    result = caption_image(chat_model, str(image_path))

    assert result == "A bar chart showing sales."
    chat_model.invoke.assert_called_once()
    (messages,), _ = chat_model.invoke.call_args
    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, HumanMessage)
    parts = message.content
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    expected_b64 = base64.b64encode(image_bytes).decode("utf-8")
    assert parts[1]["image_url"]["url"] == f"data:image/png;base64,{expected_b64}"


def test_caption_image_returns_none_on_llm_failure(tmp_path):
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"fake-jpeg-bytes")

    chat_model = MagicMock()
    chat_model.invoke.side_effect = RuntimeError("rate limited")

    result = caption_image(chat_model, str(image_path))

    assert result is None


def test_caption_image_returns_none_for_missing_file():
    chat_model = MagicMock()

    result = caption_image(chat_model, "/no/such/file.png")

    assert result is None
    chat_model.invoke.assert_not_called()


def test_caption_image_returns_none_for_blank_response(tmp_path):
    image_path = tmp_path / "blank.png"
    image_path.write_bytes(b"bytes")

    chat_model = MagicMock()
    chat_model.invoke.return_value = SimpleNamespace(content="   ")

    result = caption_image(chat_model, str(image_path))

    assert result is None
