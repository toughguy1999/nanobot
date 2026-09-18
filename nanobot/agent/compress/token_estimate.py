"""Cheap deterministic token estimates without a tokenizer."""

from __future__ import annotations

import json

IMAGE_TOKEN_ESTIMATE = 1024

# Han (including extensions and compatibility), kana, Hangul, and punctuation.
CJK_RANGES = (
    (0x1100, 0x11FF), (0x2E80, 0x2FFF), (0x3000, 0x303F),
    (0x3040, 0x30FF), (0x3130, 0x318F), (0x31A0, 0x31BF),
    (0x31F0, 0x31FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF),
    (0xA960, 0xA97F), (0xAC00, 0xD7AF), (0xD7B0, 0xD7FF),
    (0xF900, 0xFAFF), (0xFE10, 0xFE1F), (0xFE30, 0xFE4F),
    (0xFF01, 0xFF0F), (0xFF1A, 0xFF20), (0xFF3B, 0xFF40),
    (0xFF5B, 0xFF65), (0xFF66, 0xFF9F), (0xFFA0, 0xFFDC), (0xFFE0, 0xFFE6),
    (0x1AFF0, 0x1AFFF), (0x1B000, 0x1B16F),
    (0x20000, 0x2A6DF), (0x2A700, 0x2B73F), (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF), (0x2CEB0, 0x2EBEF), (0x2EBF0, 0x2EE5F),
    (0x2F800, 0x2FA1F), (0x30000, 0x3134F), (0x31350, 0x3347F),
)


def character_weight(char: str) -> int:
    code = ord(char)
    if code < 0x1100:
        return 1
    for start, end in CJK_RANGES:
        if start <= code <= end:
            return 4
    return 1


def estimate_tokens(text: str) -> int:
    return (sum(character_weight(char) for char in text) + 3) // 4


def estimate_payload_tokens(value: object) -> int:
    """Estimate one complete JSON-compatible payload."""
    normalized, image_count = _normalize_images(value)
    serialized = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return estimate_tokens(serialized) + image_count * IMAGE_TOKEN_ESTIMATE


def _normalize_images(value: object) -> tuple[object, int]:
    if isinstance(value, dict):
        if value.get("type") == "image_url" and "image_url" in value:
            return {"type": "image_url", "image_url": "<image>"}, 1
        normalized: dict[str, object] = {}
        count = 0
        for key, item in value.items():
            normalized_item, item_count = _normalize_images(item)
            normalized[str(key)] = normalized_item
            count += item_count
        return normalized, count
    if isinstance(value, list):
        normalized_items: list[object] = []
        count = 0
        for item in value:
            normalized_item, item_count = _normalize_images(item)
            normalized_items.append(normalized_item)
            count += item_count
        return normalized_items, count
    if isinstance(value, tuple):
        return _normalize_images(list(value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value, 0
    return str(value), 0
