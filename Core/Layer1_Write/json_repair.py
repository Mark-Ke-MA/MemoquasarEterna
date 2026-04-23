#!/usr/bin/env python3
"""Layer1 JSON 格式修复工具。

职责边界：
- 只修复“可机械修复”的 JSON 格式问题
- 不猜测语义，不补字段，不改 schema
- 适合给 Stage3 / Stage4 finalize 做读文件前的保守预处理

支持的最小修复策略：
1. 直接 JSON 解析
2. 去掉 markdown code fence
3. 截取首个 '{' 到最后一个 '}' 的对象片段
4. 修剪对象尾部多余的 ']' / ',' / 空白字符

明确不做：
- 不修复缺失字段
- 不补括号层级
- 不推断 key / value
- 不在多个候选 JSON 中做语义选择
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding='utf-8')


def _write_text_atomic(path: str | Path, text: str) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.tmp-', suffix=file_path.suffix or '.json', dir=str(file_path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp_path, file_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _try_parse(text: str) -> tuple[bool, Any]:
    try:
        return True, json.loads(text)
    except Exception:  # noqa: BLE001
        return False, None


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith('```'):
        return text

    lines = stripped.splitlines()
    if not lines:
        return text
    if not lines[0].startswith('```'):
        return text
    if len(lines) >= 2 and lines[-1].strip() == '```':
        return '\n'.join(lines[1:-1]).strip()
    return text


def _extract_outer_json_object(text: str) -> str | None:
    start = text.find('{')
    end = text.rfind('}')
    if start < 0 or end < 0 or end <= start:
        return None
    return text[start:end + 1]


def _trim_object_suffix_noise(text: str) -> str | None:
    candidate = _extract_outer_json_object(text)
    if candidate is None:
        return None

    tail = text[text.rfind('}') + 1:]
    if tail and any(ch not in ' \t\r\n],' for ch in tail):
        return None
    return candidate.strip()


def _normalize_candidate(text: str) -> str:
    return text.strip()


def repair_json_text(raw_text: str) -> tuple[bool, Any, str | None, str | None]:
    """尝试修复 JSON 文本。

    返回：
    - ok: 是否成功
    - payload: 解析后的对象；失败则 None
    - repaired_text: 成功时的标准文本；若无需修复则为原始规范化文本
    - method: 使用的方法名；失败则 None
    """
    if not isinstance(raw_text, str):
        return False, None, None, None

    normalized = _normalize_candidate(raw_text)
    ok, payload = _try_parse(normalized)
    if ok:
        return True, payload, normalized, 'direct'

    fenced = _strip_markdown_fence(raw_text)
    fenced_normalized = _normalize_candidate(fenced)
    if fenced_normalized != normalized:
        ok, payload = _try_parse(fenced_normalized)
        if ok:
            return True, payload, fenced_normalized, 'strip_markdown_fence'

    extracted = _extract_outer_json_object(fenced_normalized)
    if extracted is not None:
        extracted_normalized = _normalize_candidate(extracted)
        ok, payload = _try_parse(extracted_normalized)
        if ok:
            return True, payload, extracted_normalized, 'extract_outer_json_object'

    trimmed = _trim_object_suffix_noise(fenced_normalized)
    if trimmed is not None:
        trimmed_normalized = _normalize_candidate(trimmed)
        ok, payload = _try_parse(trimmed_normalized)
        if ok:
            return True, payload, trimmed_normalized, 'trim_object_suffix_noise'

    return False, None, None, None


def load_json_with_repair(path: str | Path) -> tuple[bool, Any, bool]:
    """读取 JSON 文件；若存在可机械修复的问题，则修复后原子写回。

    返回：
    - ok: 是否成功获得 JSON 对象
    - payload: 解析后的对象；失败则 None
    - repaired: 是否发生过修复写回
    """
    file_path = Path(path)
    if not file_path.exists():
        return False, None, False

    raw_text = _read_text(file_path)
    ok, payload, repaired_text, method = repair_json_text(raw_text)
    if not ok or repaired_text is None:
        return False, None, False

    normalized_original = _normalize_candidate(raw_text)
    repaired = repaired_text != normalized_original or method != 'direct'
    if repaired:
        _write_text_atomic(file_path, repaired_text)
    return True, payload, repaired


def try_repair_json_file(path: str | Path) -> bool:
    """尝试修复单个 JSON 文件；仅返回是否成功修复为合法 JSON。"""
    ok, _payload, _repaired = load_json_with_repair(path)
    return ok


__all__ = [
    'repair_json_text',
    'load_json_with_repair',
    'try_repair_json_file',
]
