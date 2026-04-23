"""Layer1 写入层共享函数。

这里只保留 Layer1 专属公共面：
- 路径拼装
- token 估算
- 批次分组
- 时间窗口推导

通用的日志 / JSON 读写 / 配置加载已统一放到 `shared_funcs.py`。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from Core.shared_funcs import CleanMemoryPaths, LoadConfig, dbg, load_json_file, output_failure, output_success, require_keys, write_json_atomic


# ---------------------------------------------------------------------------
# 路径拼装
# ---------------------------------------------------------------------------


def _store_dir_root(cfg: dict) -> str:
    return os.path.expanduser(cfg['store_dir'])


def build_store_paths(agent_id: str, cfg: dict | None = None) -> dict[str, str]:
    """为单个 agent 组装 memory / staging 的标准路径。"""
    if cfg is None:
        cfg = LoadConfig().overall_config
    store_root = _store_dir_root(cfg)
    s = cfg['store_dir_structure']
    mem = s['memory']
    stg = s['staging']

    memory_root = os.path.join(store_root, mem['root'])
    memory_agent_root = os.path.join(memory_root, agent_id)
    memory_surface_root = os.path.join(memory_agent_root, mem['surface'])
    memory_shallow_root = os.path.join(memory_agent_root, mem['shallow'])
    memory_deep_root = os.path.join(memory_agent_root, mem['deep'])

    staging_root = os.path.join(store_root, stg['root'])
    staging_surface_root = os.path.join(staging_root, stg['staging_surface'])
    staging_surface_agent_root = os.path.join(staging_surface_root, agent_id)
    staging_shallow_root = os.path.join(staging_root, stg['staging_shallow'])
    staging_deep_root = os.path.join(staging_root, stg['staging_deep'])

    return {
        'store_root': store_root,
        'memory_root': memory_root,
        'memory_agent_root': memory_agent_root,
        'memory_surface_root': memory_surface_root,
        'memory_shallow_root': memory_shallow_root,
        'memory_deep_root': memory_deep_root,
        'staging_root': staging_root,
        'staging_surface_root': staging_surface_root,
        'staging_surface_agent_root': staging_surface_agent_root,
        'staging_shallow_root': staging_shallow_root,
        'staging_deep_root': staging_deep_root,
    }


def build_layer0_artifact_paths(agent_id: str, target_date_str: str, cfg: dict | None = None) -> dict[str, str]:
    """Layer0 及后续层会消费的标准产物路径。"""
    if cfg is None:
        cfg = LoadConfig().overall_config
    store_paths = build_store_paths(agent_id, cfg)
    month_dir = os.path.join(store_paths['memory_surface_root'], target_date_str[:7])
    return {
        'month_dir': month_dir,
        'l1_path': os.path.join(month_dir, f'{target_date_str}_l1.json'),
        'l2_path': os.path.join(month_dir, f'{target_date_str}_l2.json'),
        'staging_ready_path': os.path.join(store_paths['staging_surface_agent_root'], 'extraction_ready.json'),
        'staging_alert_path': os.path.join(store_paths['staging_surface_agent_root'], 'extraction_alert.json'),
        'staging_surface_agent_root': store_paths['staging_surface_agent_root'],
    }


def build_layer1_work_paths(agent_id: str, target_date_str: str, cfg: dict | None = None) -> dict[str, str]:
    """为旧版 Layer1 规划接口返回当前主流程兼容的默认路径。"""
    if cfg is None:
        cfg = LoadConfig().overall_config
    store_paths = build_store_paths(agent_id, cfg)
    base_root = store_paths['staging_surface_agent_root']
    staging_surface_root = os.path.dirname(base_root)
    return {
        'base_root': base_root,
        'plan_path': os.path.join(staging_surface_root, 'plan.json'),
        'chunk_root': base_root,
        'map_root': base_root,
        'reduce_root': base_root,
        'reduce_output_path': os.path.join(base_root, 'reduced_results.json'),
    }


# ---------------------------------------------------------------------------
# token 估算 / 批次分组
# ---------------------------------------------------------------------------


def estimate_tokens_from_text(text: str, *, chars_per_token: int = 3) -> int:
    """按字符粗估 token 数。"""
    if not text:
        return 0
    if chars_per_token <= 0:
        raise ValueError('chars_per_token 必须为正数')
    return max(1, int(len(text) / chars_per_token))


def estimate_tokens_from_excerpts(excerpts: list[dict[str, Any]], *, chars_per_token: int = 3) -> int:
    """按 conversation_excerpts 粗估 token 数。"""
    total_chars = 0
    for excerpt in excerpts or []:
        if isinstance(excerpt, dict):
            total_chars += len(str(excerpt.get('content', '')))
        else:
            total_chars += len(str(excerpt))
    return estimate_tokens_from_text('x' * total_chars, chars_per_token=chars_per_token)


def estimate_tokens_from_file(path: str | Path, *, chars_per_token: int = 3) -> int:
    """按文件内容粗估 token 数。"""
    if not os.path.exists(path):
        return 0
    with open(path, encoding='utf-8') as f:
        return estimate_tokens_from_text(f.read(), chars_per_token=chars_per_token)


def group_into_batches(items: list[Any], batch_size: int) -> list[list[Any]]:
    """把列表按 batch_size 分批。"""
    if batch_size <= 0:
        raise ValueError('batch_size 必须为正数')
    return [items[i:i + batch_size] for i in range(0, len(items), batch_size)]


# ---------------------------------------------------------------------------
# 时间窗口
# ---------------------------------------------------------------------------


def get_previous_window_date(repo_root: str | Path | None = None) -> str:
    """根据 boundary 计算当前执行时刻所属窗口的上一个窗口日期。"""
    cfg = LoadConfig(repo_root)
    local_tz = ZoneInfo(cfg.overall_config.get('timezone', 'Europe/London'))
    boundary = cfg.overall_config.get('window', {}).get('boundary', {})
    boundary_hour = int(boundary['hour'])
    boundary_minute = int(boundary['minute'])

    now_local = datetime.now(local_tz)
    boundary_now = now_local.replace(hour=boundary_hour, minute=boundary_minute, second=0, microsecond=0)
    if now_local < boundary_now:
        current_window_start = now_local.date() - timedelta(days=1)
    else:
        current_window_start = now_local.date()
    return (current_window_start - timedelta(days=1)).strftime('%Y-%m-%d')


__all__ = [
    'CleanMemoryPaths',
    'LoadConfig',
    'dbg',
    'load_json_file',
    'output_failure',
    'output_success',
    'require_keys',
    'write_json_atomic',
    'build_store_paths',
    'build_layer0_artifact_paths',
    'build_layer1_work_paths',
    'estimate_tokens_from_text',
    'estimate_tokens_from_excerpts',
    'estimate_tokens_from_file',
    'group_into_batches',
    'get_previous_window_date',
]
