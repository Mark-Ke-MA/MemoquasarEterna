"""清洁版记忆系统共享函数。

这里只保留 MemoquasarEterna 全局复用的最小公共面：
- 调试与 JSON 输出
- 配置加载与校验
- 原子 JSON 读写
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# 日志 / JSON 读写
# ---------------------------------------------------------------------------


def dbg(msg: str):
    """把调试信息打印到 stderr，避免污染 JSON stdout。"""
    print(f"[DBG] {msg}", file=sys.stderr)


def output_success(data: dict):
    """输出成功 JSON。"""
    print(json.dumps(data, ensure_ascii=False), flush=True)


def output_failure(error: str):
    """输出失败 JSON，并以非零状态退出。"""
    print(json.dumps({'success': False, 'error': error}, ensure_ascii=False), flush=True)
    raise SystemExit(1)


def load_json_file(path: str | Path) -> Any:
    """读取 JSON 文件。"""
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_json_atomic(path: str | Path, data: Any, *, indent: int = 2):
    """原子写入 JSON。"""
    path = str(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


def _nonempty_str(value: Any) -> str:
    return str(value or '').strip()


def get_memory_worker_agent_id(overall_config: dict[str, Any]) -> str:
    agent_id = _nonempty_str(overall_config.get('memory_worker_agentId'))
    if not agent_id:
        raise KeyError('OverallConfig.json 缺少 memory_worker_agentId')
    return agent_id


def get_memory_worker_harness(overall_config: dict[str, Any]) -> str:
    harness = _nonempty_str(overall_config.get('memory_worker_harness'))
    if not harness:
        raise KeyError('OverallConfig.json 缺少 memory_worker_harness')
    return harness


def get_production_agents(overall_config: dict[str, Any]) -> list[dict[str, str]]:
    raw_agents = overall_config.get('production_agents')
    if not isinstance(raw_agents, list) or not raw_agents:
        raise KeyError('OverallConfig.json 缺少 production_agents 或其为空')

    parsed: list[dict[str, str]] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw_agents):
        if not isinstance(item, dict):
            raise ValueError(f'OverallConfig.json.production_agents[{idx}] 必须是 object')
        agent_id = _nonempty_str(item.get('agentId'))
        harness = _nonempty_str(item.get('harness'))
        if not agent_id:
            raise ValueError(f'OverallConfig.json.production_agents[{idx}] 缺少 agentId')
        if not harness:
            raise ValueError(f'OverallConfig.json.production_agents[{idx}] 缺少 harness')
        if agent_id in seen:
            raise ValueError(f'OverallConfig.json.production_agents 中存在重复 agentId: {agent_id}')
        seen.add(agent_id)
        parsed.append({'agentId': agent_id, 'harness': harness})
    return parsed


def get_production_agent_ids(overall_config: dict[str, Any]) -> list[str]:
    return [item['agentId'] for item in get_production_agents(overall_config)]


def get_production_agent_harness(overall_config: dict[str, Any], agent_id: str) -> str:
    target = _nonempty_str(agent_id)
    for item in get_production_agents(overall_config):
        if item['agentId'] == target:
            return item['harness']
    raise KeyError(f'OverallConfig.json.production_agents 中不存在 agentId: {target}')


def group_production_agents_by_harness(overall_config: dict[str, Any], agent_ids: Iterable[str] | None = None) -> dict[str, list[str]]:
    allowed = None if agent_ids is None else {_nonempty_str(item) for item in agent_ids if _nonempty_str(item)}
    groups: dict[str, list[str]] = {}
    known: set[str] = set()
    for item in get_production_agents(overall_config):
        agent_id = item['agentId']
        known.add(agent_id)
        if allowed is not None and agent_id not in allowed:
            continue
        groups.setdefault(item['harness'], []).append(agent_id)
    if allowed is not None:
        unknown = sorted(allowed - known)
        if unknown:
            raise ValueError(f'未知 production agent: {", ".join(unknown)}')
    return groups


def parse_selected_production_agent_ids(overall_config: dict[str, Any], agent: str | None) -> list[str]:
    all_agents = get_production_agent_ids(overall_config)
    if agent is None or not str(agent).strip():
        return all_agents
    selected: list[str] = []
    seen: set[str] = set()
    for item in str(agent).split(','):
        agent_id = item.strip()
        if not agent_id or agent_id in seen:
            continue
        if agent_id not in all_agents:
            raise ValueError(f'未知 agent: {agent_id}')
        seen.add(agent_id)
        selected.append(agent_id)
    if not selected:
        raise ValueError('--agent 解析后为空')
    return selected


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CleanMemoryPaths:
    """clean 版路径信息。"""

    repo_root: Path
    code_root: str
    store_root: str
    overall_config: dict[str, Any]


class LoadConfig:
    """加载 clean 版总配置。"""

    def __init__(self, repo_root: str | Path | None = None):
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
        self.overall_config = self.load_overall_config()
        self.code_root = os.path.expanduser(self.overall_config['code_dir'])
        self.store_root = os.path.expanduser(self.overall_config['store_dir'])

    def load_overall_config(self) -> dict:
        path = self.repo_root / 'OverallConfig.json'
        if not path.exists():
            raise FileNotFoundError(f'OverallConfig.json 不存在: {path}')
        data = load_json_file(path)
        if not isinstance(data, dict):
            raise ValueError(f'OverallConfig.json 格式错误: {path}')
        for key in ('memory_worker_agentId', 'memory_worker_harness', 'production_agents', 'code_dir', 'store_dir', 'store_dir_structure', 'window', 'layer1_write', 'active_schema_version', 'archive_schema_version'):
            if key not in data:
                raise KeyError(f'OverallConfig.json 缺少 {key}')
        get_memory_worker_agent_id(data)
        get_memory_worker_harness(data)
        get_production_agents(data)
        return data


def require_keys(data: dict, keys: Iterable[str], *, where: str = 'config'):
    """检查字典是否包含必需键。"""
    missing = [key for key in keys if key not in data]
    if missing:
        raise KeyError(f'{where} 缺少键: {", ".join(missing)}')


__all__ = [
    'dbg',
    'output_success',
    'output_failure',
    'load_json_file',
    'write_json_atomic',
    'get_memory_worker_agent_id',
    'get_memory_worker_harness',
    'get_production_agents',
    'get_production_agent_ids',
    'get_production_agent_harness',
    'group_production_agents_by_harness',
    'parse_selected_production_agent_ids',
    'CleanMemoryPaths',
    'LoadConfig',
    'require_keys',
]
