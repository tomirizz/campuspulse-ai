"""Strict JSON envelopes for provider responses, never arbitrary text extraction."""
import json
import re


def parse_json_response(raw: str, *, max_chars: int = 45_000):
    """Accept one entire JSON document, optionally in one complete code fence.

    Parsing is not validation: callers must still validate their own schema and
    evidence. Text surrounding JSON and multiple fenced blocks are rejected.
    """
    if not isinstance(raw, str) or not 1 <= len(raw) <= max_chars:
        raise ValueError("Пустой или слишком большой ответ")
    text = raw.strip()
    fenced = re.fullmatch(r"\x60{3}(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n\x60{3}", text, re.I)
    if fenced:
        text = fenced[1].strip()
    return json.loads(text)
