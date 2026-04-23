#!/usr/bin/env python3
"""Layer2_Preserve shared helpers."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from Core.shared_funcs import LoadConfig, load_json_file, write_json_atomic
from Core.Layer1_Write.shared import build_store_paths


def parse_iso_date(text: str) -> date:
    return datetime.strptime(text, '%Y-%m-%d').date()


def iso_week_id(day: date) -> str:
    iso_year, iso_week, _ = day.isocalendar()
    return f'{iso_year}-W{iso_week:02d}'


def previous_iso_week_anchor(today: date) -> date:
    weekday = today.isoweekday()
    current_week_monday = today - timedelta(days=weekday - 1)
    return current_week_monday - timedelta(days=7)


def iso_week_window_from_anchor(anchor: date) -> tuple[date, date]:
    monday = anchor - timedelta(days=anchor.isoweekday() - 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def store_surface_root(agent_id: str, overall_config: dict[str, Any]) -> Path:
    return Path(build_store_paths(agent_id, overall_config)['memory_surface_root'])


def stage_preserve_marker_path(agent_id: str, overall_config: dict[str, Any], marker_filename: str) -> Path:
    return store_surface_root(agent_id, overall_config) / marker_filename


def normalize_for_json(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [normalize_for_json(item) for item in value]
    if isinstance(value, list):
        return [normalize_for_json(item) for item in value]
    if isinstance(value, dict):
        return {str(k): normalize_for_json(v) for k, v in value.items()}
    return value


__all__ = [
    'LoadConfig',
    'load_json_file',
    'write_json_atomic',
    'parse_iso_date',
    'iso_week_id',
    'previous_iso_week_anchor',
    'iso_week_window_from_anchor',
    'utc_now_iso',
    'store_surface_root',
    'stage_preserve_marker_path',
    'normalize_for_json',
]
