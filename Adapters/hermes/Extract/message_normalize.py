#!/usr/bin/env python3
"""Hermes state.db message normalization."""
from __future__ import annotations

import re


REDACT_PATTERNS = [
    re.compile(r'(sk-|pk-|api[-_]?key[\s=:]+)\S{10,}', re.IGNORECASE),
    re.compile(r'\b1[3-9]\d{9}\b'),
    re.compile(r'\b[\w.+-]+@[\w.-]+\.\w{2,}\b'),
    re.compile(r'\b\d{9,10}\b'),
    re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
]


def redact(text: str) -> str:
    for pattern in REDACT_PATTERNS:
        text = pattern.sub('[REDACTED]', text)
    return text


def normalize_message_content(role: str, content: str | None) -> str:
    if role not in {'user', 'assistant'}:
        return ''
    text = str(content or '').strip()
    if not text:
        return ''
    return redact(text)
