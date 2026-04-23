#!/usr/bin/env python3
"""OpenClaw 专属消息清洗：metadata envelope、audio wrapper、message type 判定。"""
import re

REDACT_PATTERNS = [
    re.compile(r'(sk-|pk-|api[-_]?key[\s=:]+)\S{10,}', re.IGNORECASE),
    re.compile(r'\b1[3-9]\d{9}\b'),
    re.compile(r'\b[\w.+-]+@[\w.-]+\.\w{2,}\b'),
    re.compile(r'\b\d{9,10}\b'),
    re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
]


def redact(text: str) -> str:
    """屏蔽看起来像密钥、手机号、邮箱、IP 的片段。"""
    for pattern in REDACT_PATTERNS:
        text = pattern.sub('[REDACTED]', text)
    return text


def strip_openclaw_user_metadata_envelope(text: str) -> str:
    """去掉 OpenClaw 注入到 user 文本前面的 untrusted metadata header。"""
    if not text or not text.startswith('Conversation info (untrusted metadata):'):
        return text
    pattern = re.compile(
        r'^Conversation info \(untrusted metadata\):\s*```json\s*.*?```\s*'
        r'Sender \(untrusted metadata\):\s*```json\s*.*?```\s*',
        re.DOTALL,
    )
    stripped = pattern.sub('', text, count=1).strip()
    return stripped or text


def normalize_audio_transcript_block(text: str) -> str:
    """优先提取 ASR 后的 User text；失败时回退到 Transcript。"""
    if not text or '[Audio]' not in text:
        return text

    if 'User text:' in text and 'Transcript:' in text:
        user_part = text.split('User text:', 1)[1].split('Transcript:', 1)[0].strip()
        if user_part:
            lines = [ln.rstrip() for ln in user_part.splitlines() if ln.strip()]
            if lines and lines[0].startswith('[Telegram '):
                first = lines[0]
                closing = first.find(']')
                if closing != -1:
                    remainder = first[closing + 1:].strip()
                    if remainder:
                        lines[0] = remainder
                    else:
                        lines = lines[1:]
            cleaned = '\n'.join(ln.strip() for ln in lines if ln.strip()).strip()
            if cleaned:
                return cleaned

    if 'Transcript:' in text:
        transcript = text.split('Transcript:', 1)[1].strip()
        if transcript:
            return transcript

    return text


REPLY_TAG_PATTERN = re.compile(r'^(?:\[\[reply_to_current\]\]|\[\[reply_to:[^\]]+\]\])(?:\s|\n|\r|\t)*', re.MULTILINE)


def strip_reply_tag_prefix(text: str) -> str:
    """去掉 OpenClaw native reply tag 前缀（如 [[reply_to_current]] / [[reply_to:<id>]]）。"""
    if not text:
        return text
    stripped = text
    while True:
        new_text = REPLY_TAG_PATTERN.sub('', stripped, count=1).lstrip()
        if new_text == stripped:
            return stripped
        stripped = new_text


def detect_message_type(text: str, role: str | None = None) -> str:
    """把 OpenClaw 特有的文本标成 text / audio。"""
    if role == 'assistant':
        return 'text'
    if not text or role != 'user':
        return 'text'
    if '[Audio]' in text and 'User text:' in text and 'Transcript:' in text and '[Telegram ' in text:
        return 'audio'
    return 'text'


def clean_user_text(text: str) -> tuple[str, str]:
    """把 user 原文清洗成标准文本，并返回清洗后的 message_type。"""
    text = strip_openclaw_user_metadata_envelope(text)
    text = strip_reply_tag_prefix(text)
    message_type = detect_message_type(text, 'user')
    if message_type == 'audio':
        text = normalize_audio_transcript_block(text)
    return redact(text), message_type


