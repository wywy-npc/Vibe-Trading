"""Shared YAML frontmatter parser for skills and memory files."""

from __future__ import annotations

import re
from typing import Any, Dict

import yaml


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter and body from a markdown file.

    Supports the full YAML 1.1 grammar via ``yaml.safe_load``: scalars, lists,
    nested mappings, booleans, and quoted strings. Returns ``({}, body)`` when
    no frontmatter delimiter is found or the YAML block fails to parse.

    Args:
        text: Markdown text with optional ``---`` delimited frontmatter.

    Returns:
        Tuple of (metadata dict, body text).
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()

    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text.strip()

    if not isinstance(meta, dict):
        meta = {}
    return meta, match.group(2).strip()
