#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

"""Layer4 recent fallback helpers.

职责：
- 在未提供 query 时，按 recent_days 直接读取最近 N 天 surface L1
- 按天组装 summary / topics / decisions / todos / key_items
- 遵循分档规则控制字段粒度，并在全局 max_chars 下做优先级截断

当前规则：
1. recent_days 必须 > 0
2. 0 < N <= 3：summary + topics + decisions + todos + key_items
3. 3 < N <= 7：summary + topics
4. 7 < N：summary
5. 全局截断优先级：decisions/todos -> key_items -> topics -> summary
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from Core.shared_funcs import LoadConfig


DEFAULT_RECENT_DAYS = 3


@dataclass(slots=True)
class _DayView:
    date: str
    source_path: str
    summary: str
    topics: list[str]
    decisions: list[str]
    todos: list[str]
    key_items: list[str]


def _current_local_date(overall_config: dict[str, Any]) -> date:
    tz_name = str(overall_config.get('timezone', 'Europe/London') or 'Europe/London')
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo('Europe/London')
    return datetime.now(tz).date()


def _memory_surface_root(agent_id: str, overall_config: dict[str, Any]) -> Path:
    store_root = Path(str(overall_config['store_dir'])).expanduser()
    structure = overall_config.get('store_dir_structure', {}) if isinstance(overall_config, dict) else {}
    memory_cfg = structure.get('memory', {}) if isinstance(structure, dict) else {}
    memory_root = str(memory_cfg.get('root', 'memory') or 'memory')
    surface_dir = str(memory_cfg.get('surface', 'surface') or 'surface')
    return store_root / memory_root / agent_id / surface_dir


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding='utf-8') as f:
            payload = json.load(f)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return str(value).strip()


def _parse_recent_days(value: int) -> int:
    days = int(value)
    if days <= 0:
        raise ValueError('recent_days 必须满足 N > 0')
    return days


def _recent_dates(*, today: date, recent_days: int) -> list[str]:
    return [
        (today - timedelta(days=offset + 1)).strftime('%Y-%m-%d')
        for offset in range(max(0, recent_days))
    ]


def _resolve_surface_l1_path(surface_root: Path, target_date: str) -> Path:
    return surface_root / target_date[:7] / f'{target_date}_l1.json'


def _format_topic(item: Any) -> str:
    if isinstance(item, dict):
        name = _normalize_text(item.get('name'))
        detail = _normalize_text(item.get('detail'))
        if name and detail:
            return f'{name}: {detail}'
        return name or detail
    return _normalize_text(item)


def _format_key_item(item: Any) -> str:
    if isinstance(item, dict):
        desc = _normalize_text(item.get('desc'))
        kind = _normalize_text(item.get('type'))
        if kind and desc:
            return f'[{kind}] {desc}'
        return desc or kind
    return _normalize_text(item)


def _load_day_view(path: Path, target_date: str) -> _DayView | None:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return None

    topics_raw = payload.get('topics', [])
    decisions_raw = payload.get('decisions', [])
    todos_raw = payload.get('todos', [])
    key_items_raw = payload.get('key_items', [])

    topics = []
    if isinstance(topics_raw, list):
        topics = [text for text in (_format_topic(item) for item in topics_raw) if text]

    decisions = []
    if isinstance(decisions_raw, list):
        decisions = [text for text in (_normalize_text(item) for item in decisions_raw) if text]

    todos = []
    if isinstance(todos_raw, list):
        todos = [text for text in (_normalize_text(item) for item in todos_raw) if text]

    key_items = []
    if isinstance(key_items_raw, list):
        key_items = [text for text in (_format_key_item(item) for item in key_items_raw) if text]

    return _DayView(
        date=target_date,
        source_path=str(path),
        summary=_normalize_text(payload.get('summary')),
        topics=topics,
        decisions=decisions,
        todos=todos,
        key_items=key_items,
    )


def _field_tier_for_recent_days(recent_days: int) -> dict[str, bool]:
    if recent_days <= 3:
        return {
            'summary': True,
            'topics': True,
            'decisions': True,
            'todos': True,
            'key_items': True,
        }
    if recent_days <= 7:
        return {
            'summary': True,
            'topics': True,
            'decisions': False,
            'todos': False,
            'key_items': False,
        }
    return {
        'summary': True,
        'topics': False,
        'decisions': False,
        'todos': False,
        'key_items': False,
    }


def _overview_line(day: _DayView) -> str:
    summary = day.summary or '（无摘要）'
    return f'- {day.date}: {summary}'


def _truncate_to_fit(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return '…'[:max_len]
    return text[: max_len - 1].rstrip() + '…'


def _render_recent_text(*, days: list[_DayView], field_tier: dict[str, bool], max_chars: int) -> str:
    max_len = max(1, int(max_chars))
    parts: list[str] = []
    current_len = 0

    def _try_append(line: str) -> bool:
        nonlocal current_len
        addition = line if not parts else '\n' + line
        if current_len + len(addition) > max_len:
            return False
        parts.append(line)
        current_len += len(addition)
        return True

    def _append_forced(line: str) -> None:
        nonlocal current_len
        if not parts:
            trimmed = _truncate_to_fit(line, max_len)
            parts.append(trimmed)
            current_len = len(trimmed)
            return
        remaining = max_len - current_len - 1
        if remaining <= 0:
            return
        trimmed = _truncate_to_fit(line, remaining)
        parts.append(trimmed)
        current_len += 1 + len(trimmed)

    if not _try_append('### 最近记忆概览'):
        return _truncate_to_fit('### 最近记忆概览', max_len)

    overview_lines = [_overview_line(day) for day in days]
    for line in overview_lines:
        if not _try_append(line):
            break

    for day in days:
        if not _try_append(f'[{day.date}]'):
            break

        if field_tier.get('summary', False):
            summary_line = f'摘要：{day.summary or "（无摘要）"}'
            if not _try_append(summary_line):
                _append_forced(summary_line)
                break

        if field_tier.get('topics', False) and day.topics:
            if not _try_append('主题：'):
                break
            for item in day.topics:
                if not _try_append(f'- {item}'):
                    return '\n'.join(parts).strip()

        if field_tier.get('key_items', False) and day.key_items:
            if not _try_append('关键事项：'):
                break
            for item in day.key_items:
                if not _try_append(f'- {item}'):
                    return '\n'.join(parts).strip()

        if field_tier.get('decisions', False) and day.decisions:
            if not _try_append('决策：'):
                break
            for item in day.decisions:
                if not _try_append(f'- {item}'):
                    return '\n'.join(parts).strip()

        if field_tier.get('todos', False) and day.todos:
            if not _try_append('待办：'):
                break
            for item in day.todos:
                if not _try_append(f'- {item}'):
                    return '\n'.join(parts).strip()

    return '\n'.join(parts).strip()


def recall_recent(*, repo_root: str | None = None, agent_id: str, recent_days: int = DEFAULT_RECENT_DAYS, max_chars: int) -> dict[str, Any]:
    cfg = LoadConfig(repo_root)
    overall_config = cfg.overall_config
    today = _current_local_date(overall_config)
    resolved_recent_days = _parse_recent_days(recent_days)
    field_tier = _field_tier_for_recent_days(resolved_recent_days)
    surface_root = _memory_surface_root(agent_id, overall_config)

    requested_dates = _recent_dates(today=today, recent_days=resolved_recent_days)
    found_days: list[_DayView] = []
    missing_dates: list[str] = []

    for target_date in requested_dates:
        path = _resolve_surface_l1_path(surface_root, target_date)
        day = _load_day_view(path, target_date)
        if day is None:
            missing_dates.append(target_date)
            continue
        found_days.append(day)

    assembled_text = _render_recent_text(
        days=found_days,
        field_tier=field_tier,
        max_chars=max_chars,
    )

    return {
        'success': True,
        'mode': 'recent_fallback',
        'agent_id': agent_id,
        'today': today.strftime('%Y-%m-%d'),
        'recent_days': resolved_recent_days,
        'date_window': None,
        'field_tier': {
            key: value
            for key, value in field_tier.items()
            if value
        },
        'requested_dates': requested_dates,
        'missing_dates': missing_dates,
        'days': [
            {
                'date': day.date,
                'source_path': day.source_path,
                'summary': day.summary,
                'topics': day.topics if field_tier.get('topics', False) else [],
                'decisions': day.decisions if field_tier.get('decisions', False) else [],
                'todos': day.todos if field_tier.get('todos', False) else [],
                'key_items': day.key_items if field_tier.get('key_items', False) else [],
            }
            for day in found_days
        ],
        'assembled_text': assembled_text,
        'note': 'Layer4 recent fallback 执行完成。',
    }


__all__ = ['recall_recent', 'DEFAULT_RECENT_DAYS']
