"""Shared: ask model for JSON and validate as CommandBatch."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.core.commands import CommandBatch


def extract_json_object(text: str) -> dict[str, Any]:
    """Strip optional markdown fences and parse first JSON object."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t)
    if fence:
        t = fence.group(1).strip()
    # First { ... } block
    start = t.find("{")
    if start == -1:
        raise ValueError("No JSON object in model output")
    depth = 0
    for i in range(start, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                chunk = t[start : i + 1]
                return json.loads(chunk)
    raise ValueError("Unbalanced JSON in model output")


def parse_command_batch(raw_text: str) -> CommandBatch:
    data = extract_json_object(raw_text)
    return CommandBatch.model_validate(data)


def parse_command_batch_lenient(raw_text: str) -> CommandBatch:
    try:
        return parse_command_batch(raw_text)
    except (json.JSONDecodeError, ValidationError, ValueError) as e:
        raise ValueError(f"Invalid CommandBatch JSON: {e}") from e
