from __future__ import annotations

"""
Image encoding for multimodal tasks.

Encodes local image files as base64 data URIs for OpenRouter vision models.
The encoded content is embedded directly in the user message as an
OpenAI-compatible content array:

  [
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
    {"type": "text", "text": "describe this screenshot"},
  ]

Supported formats: PNG, JPEG, GIF, WEBP.
"""

import base64
import mimetypes
from pathlib import Path

_SUPPORTED = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_MIME_FALLBACK = "image/png"


def encode_image(path: str | Path) -> dict:
    """Return an OpenAI-style image_url content block for a local file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    suffix = p.suffix.lower()
    if suffix not in _SUPPORTED:
        raise ValueError(f"Unsupported image format {suffix!r}. Supported: {', '.join(_SUPPORTED)}")

    mime = mimetypes.types_map.get(suffix, _MIME_FALLBACK)
    data = base64.b64encode(p.read_bytes()).decode()
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{data}"},
    }


def build_multimodal_task(text: str, image_paths: list[str]) -> str | list[dict]:
    """
    Build the task payload for session.run().

    Returns a plain string when no images are provided (common case).
    Returns a content array when images are attached so envelope_codec
    can pass it through as-is to the API.
    """
    if not image_paths:
        return text
    blocks: list[dict] = [encode_image(p) for p in image_paths]
    blocks.append({"type": "text", "text": text})
    return blocks  # type: ignore[return-value]
