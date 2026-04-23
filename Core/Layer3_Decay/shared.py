#!/usr/bin/env python3
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from Core.shared_funcs import LoadConfig, load_json_file, write_json_atomic
from Core.Layer1_Write.shared import build_store_paths


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_iso_date(text: str) -> date:
    return datetime.strptime(text, '%Y-%m-%d').date()


def iso_week_id(day: date) -> str:
    iso_year, iso_week, _ = day.isocalendar()
    return f'{iso_year}-W{iso_week:02d}'


def monday_of_iso_week(week_id: str) -> date:
    return datetime.strptime(f'{week_id}-1', '%G-W%V-%u').date()


def previous_iso_week_id(now_local: datetime | None = None, timezone_name: str = 'Europe/London') -> str:
    if now_local is None:
        now_local = datetime.now(ZoneInfo(timezone_name))
    weekday = now_local.date().isoweekday()
    current_week_monday = now_local.date() - timedelta(days=weekday - 1)
    previous_week_monday = current_week_monday - timedelta(days=7)
    return iso_week_id(previous_week_monday)


def selected_agents(agent: str | None, all_agents: list[str]) -> list[str]:
    if agent is None or not str(agent).strip():
        return list(all_agents)
    parsed: list[str] = []
    seen: set[str] = set()
    for item in str(agent).split(','):
        item = item.strip()
        if not item or item in seen:
            continue
        if item not in all_agents:
            raise ValueError(f'未知 agent: {item}')
        seen.add(item)
        parsed.append(item)
    if not parsed:
        raise ValueError('--agent 解析后为空')
    return parsed


def surface_root(agent_id: str, overall_config: dict[str, Any]) -> Path:
    return Path(build_store_paths(agent_id, overall_config)['memory_surface_root'])


def month_dirs_under(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted([item for item in root.iterdir() if item.is_dir()])


__all__ = [
    'LoadConfig',
    'load_json_file',
    'write_json_atomic',
    'utc_now_iso',
    'parse_iso_date',
    'iso_week_id',
    'monday_of_iso_week',
    'previous_iso_week_id',
    'selected_agents',
    'surface_root',
    'month_dirs_under',
]
