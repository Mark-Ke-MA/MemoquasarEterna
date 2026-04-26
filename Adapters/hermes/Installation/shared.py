#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from Adapters.hermes.hermes_shared_funcs import LoadConfig, profile_dir_path


SKILL_NAME = 'memoquasar-memory-recall'


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[3]


def adapter_root(repo_root: Path) -> Path:
    return repo_root / 'Adapters' / 'hermes'


def hermes_config_path(repo_root: Path) -> Path:
    return adapter_root(repo_root) / 'HermesConfig.json'


def hermes_config_template_path(repo_root: Path) -> Path:
    return adapter_root(repo_root) / 'HermesConfig-template.json'


def load_config(repo_root: Path) -> LoadConfig:
    return LoadConfig(repo_root)


def output_success(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def production_agent_ids(config: LoadConfig, agent_ids: list[str] | None = None) -> list[str]:
    if agent_ids is not None:
        return [str(item).strip() for item in agent_ids if str(item).strip()]
    agents = config.overall_config.get('production_agents')
    if not isinstance(agents, list):
        raise ValueError('OverallConfig.json 缺少 production_agents list。')
    result: list[str] = []
    for item in agents:
        if not isinstance(item, dict):
            continue
        if str(item.get('harness', '') or '').strip().lower() != 'hermes':
            continue
        agent_id = str(item.get('agentId', '') or '').strip()
        if agent_id:
            result.append(agent_id)
    if not result:
        raise ValueError('未找到 harness=hermes 的 production_agents。')
    return result


def profile_dir(config: LoadConfig, agent_id: str) -> Path:
    return profile_dir_path(config, agent_id)


def skill_template_path(repo_root: Path) -> Path:
    return adapter_root(repo_root) / 'Read' / 'skills' / SKILL_NAME / 'SKILL.md.template'


def recall_entry_path(repo_root: Path) -> Path:
    return adapter_root(repo_root) / 'Read' / 'memoquasar_recall.py'


def installed_skill_dir(config: LoadConfig, agent_id: str) -> Path:
    return profile_dir(config, agent_id) / 'skills' / SKILL_NAME


def render_skill(repo_root: Path, agent_id: str) -> str:
    template = skill_template_path(repo_root).read_text(encoding='utf-8')
    return (
        template
        .replace('__PYTHON_BIN__', sys.executable)
        .replace('__RECALL_ENTRY__', str(recall_entry_path(repo_root)))
        .replace('__AGENT_ID__', str(agent_id).strip())
    )


def write_text(path: Path, text: str, *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {'changed': True, 'status': 'would-write', 'path': str(path)}
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding='utf-8') if path.exists() else None
    if old == text:
        return {'changed': False, 'status': 'unchanged', 'path': str(path)}
    path.write_text(text, encoding='utf-8')
    return {'changed': True, 'status': 'written', 'path': str(path)}


def remove_tree(path: Path, *, dry_run: bool) -> dict[str, Any]:
    if not path.exists():
        return {'changed': False, 'status': 'absent', 'path': str(path)}
    if dry_run:
        return {'changed': True, 'status': 'would-remove', 'path': str(path)}
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return {'changed': True, 'status': 'removed', 'path': str(path)}
