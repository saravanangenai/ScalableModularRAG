import base64
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from packages.observability import get_logger

logger = get_logger(__name__)

_CAPTION_PROMPT = (
    "Describe this image for a document search index. Cover: (1) what the image depicts, "
    "(2) any visible text, labels, or numbers, and (3) its likely purpose in a business, "
    "contract, or technical document. Be concise and factual."
)


def caption_image(chat_model: ChatOpenAI, image_path: str) -> str | None:
    """Vision-captions one extracted image (specs/050-vision-captioning). Never raises — a
    captioning failure (API error, timeout, content-policy refusal) degrades to None so the
    caller falls back to OCR-only text, matching
    packages/parsing/pdf_parser.py::run_ocr_on_image's "never fail the whole parse over one
    bad image" contract.
    """
    try:
        path = Path(image_path)
        image_bytes = path.read_bytes()
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        media_type = f"image/{path.suffix.lstrip('.').lower() or 'png'}"

        message = HumanMessage(
            content=[
                {"type": "text", "text": _CAPTION_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                },
            ]
        )
        response = chat_model.invoke([message])
        caption = str(response.content).strip()
        return caption or None
    except Exception as exc:
        logger.warning("vision_caption_failed", image_path=image_path, error=str(exc))
        return None
