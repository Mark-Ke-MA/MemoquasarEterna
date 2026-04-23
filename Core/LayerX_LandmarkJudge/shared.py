#!/usr/bin/env python3
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from Core.shared_funcs import LoadConfig, load_json_file


def parse_iso_date(text: str):
    return datetime.strptime(text, '%Y-%m-%d').date()


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


def landmark_scores_path(agent_id: str, overall_config: dict[str, Any]) -> Path:
    store_root = Path(os.path.expanduser(str(overall_config['store_dir'])))
    stats_cfg = overall_config['store_dir_structure']['statistics']
    return store_root / stats_cfg['root'] / stats_cfg['landmark_scores'] / f'{agent_id}_landmark_scores.json'


def resolve_graphs_dir(*, repo_root: str | Path | None, graphs_path: str | None) -> Path:
    cfg = LoadConfig(repo_root)
    overall_config = cfg.overall_config
    store_root = Path(os.path.expanduser(str(overall_config['store_dir'])))
    stats_cfg = overall_config['store_dir_structure']['statistics']
    default_root = store_root / stats_cfg['root'] / stats_cfg['graphs']

    if graphs_path is None or not str(graphs_path).strip():
        return default_root

    raw = os.path.expanduser(str(graphs_path).strip())
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    return default_root / candidate


__all__ = [
    'LoadConfig',
    'load_json_file',
    'parse_iso_date',
    'selected_agents',
    'landmark_scores_path',
    'resolve_graphs_dir',
]
