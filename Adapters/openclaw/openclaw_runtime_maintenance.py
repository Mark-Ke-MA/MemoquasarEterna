#!/usr/bin/env python3
"""OpenClaw Layer1 Write harness maintenance.

职责：
- 读取 OverallConfig.json 与 OpenclawConfig.json
- 定位 memory worker 的 sessions 目录
- 校验 memory worker 不能与日常 agent 共用
- 若目标目录存在，则安全清空其内容；不存在则跳过
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_ROOT = Path(__file__).resolve().parent
OVERALL_CONFIG_PATH = REPO_ROOT / 'OverallConfig.json'
OPENCLAW_CONFIG_PATH = ADAPTER_ROOT / 'OpenclawConfig.json'


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f'配置文件不存在: {path}')
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f'配置文件格式错误，期望 JSON object: {path}')
    return data


def _validate_memory_worker_agent_id(memory_worker_agent_id: str, agent_id_list: list[str]) -> None:
    if not memory_worker_agent_id:
        raise ValueError('memory_worker_agentId 不能为空')
    if '/' in memory_worker_agent_id or '\\' in memory_worker_agent_id:
        raise ValueError('memory_worker_agentId 不能包含路径分隔符')
    if memory_worker_agent_id in agent_id_list:
        raise ValueError('memory_worker_agentId 必须是独立的非日常 agent，不能出现在 agentId_list 中')


def _resolve_memory_worker_sessions_dir() -> Path:
    overall_cfg = _load_json_dict(OVERALL_CONFIG_PATH)
    openclaw_cfg = _load_json_dict(OPENCLAW_CONFIG_PATH)

    memory_worker_agent_id = str(overall_cfg.get('memory_worker_agentId', '') or '').strip()
    agent_id_list = [str(agent_id).strip() for agent_id in (overall_cfg.get('agentId_list', []) or []) if str(agent_id).strip()]
    _validate_memory_worker_agent_id(memory_worker_agent_id, agent_id_list)

    sessions_path_template = str(openclaw_cfg.get('sessions_path', '') or '').strip()
    if not sessions_path_template:
        raise ValueError('OpenclawConfig.json 缺少 sessions_path')

    code_dir = str(overall_cfg.get('code_dir', '') or '').strip()
    store_dir = str(overall_cfg.get('store_dir', '') or '').strip()
    adapter_dirname = str(openclaw_cfg.get('adapter_dirname', ADAPTER_ROOT.name) or ADAPTER_ROOT.name)
    sessions_path = sessions_path_template.format(
        agentId=memory_worker_agent_id,
        code_dir=code_dir,
        store_dir=store_dir,
        adapter_dirname=adapter_dirname,
    )
    return Path(sessions_path).expanduser()


def openclaw_harness_maintenance() -> dict[str, Any]:
    sessions_dir = _resolve_memory_worker_sessions_dir()
    if not sessions_dir.exists():
        return {
            'success': True,
            'skipped': True,
            'reason': 'sessions_dir_not_found',
            'sessions_dir': str(sessions_dir),
        }
    if not sessions_dir.is_dir():
        raise ValueError(f'memory worker sessions 目标路径不是目录: {sessions_dir}')

    deleted_entries: list[str] = []
    for child in list(sessions_dir.iterdir()):
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        deleted_entries.append(str(child))

    return {
        'success': True,
        'skipped': False,
        'reason': None,
        'sessions_dir': str(sessions_dir),
        'deleted_count': len(deleted_entries),
    }


__all__ = ['openclaw_harness_maintenance']



def openclaw_harness_maintenance_hook(context: dict):
    _ = context
    return openclaw_harness_maintenance()
