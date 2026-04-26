#!/usr/bin/env python3
"""Hermes adapter shared helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LoadConfig:
    def __init__(self, repo_root: str | Path | None = None):
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
        self.adapter_root = Path(__file__).resolve().parent
        self.overall_config = self.load_overall_config()
        self.hermes_config = self.load_hermes_config()

    def load_json_file(self, path: str | Path) -> dict[str, Any]:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f'JSON 顶层必须是 object: {path}')
        return data

    def load_overall_config(self) -> dict[str, Any]:
        return self.load_json_file(self.repo_root / 'OverallConfig.json')

    def load_hermes_config(self) -> dict[str, Any]:
        path = self.adapter_root / 'HermesConfig.json'
        if not path.exists():
            raise FileNotFoundError(f'HermesConfig.json 不存在: {path}')
        data = self.load_json_file(path)
        schema_version = str(data.get('schema_version', '') or '').strip()
        if not schema_version:
            raise KeyError(f'HermesConfig.json 缺少 schema_version: {path}')
        profiles_root = str(data.get('profiles_root', '') or '').strip()
        if not profiles_root:
            raise KeyError(f'HermesConfig.json 缺少 profiles_root: {path}')
        state_db_name = str(data.get('state_db_name', '') or '').strip()
        if not state_db_name:
            raise KeyError(f'HermesConfig.json 缺少 state_db_name: {path}')
        return data


def profile_state_db_path(config: LoadConfig, agent_id: str) -> Path:
    profile = str(agent_id or '').strip()
    if not profile:
        raise ValueError('Hermes agent_id/profile 不能为空')
    profiles_root = Path(str(config.hermes_config['profiles_root'])).expanduser()
    state_db_name = str(config.hermes_config['state_db_name']).strip()
    return profiles_root / profile / state_db_name
