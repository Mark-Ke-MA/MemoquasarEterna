#!/usr/bin/env python3
"""Layer0 预处理：只负责把目标日期翻译成标准时间窗口，并解析全局路径配置。"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CONFIG_PATH = Path(__file__).resolve().parents[2] / 'OverallConfig.json'
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.shared_funcs import get_production_agents


def load_overall_config() -> dict:
    """读取 OverallConfig.json；缺失或格式错误时直接报错。"""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f'OverallConfig.json 不存在: {CONFIG_PATH}')
    with open(CONFIG_PATH, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f'OverallConfig.json 格式错误: {CONFIG_PATH}')
    get_production_agents(data)
    if 'code_dir' not in data:
        raise KeyError('OverallConfig.json 缺少 code_dir')
    if 'store_dir' not in data:
        raise KeyError('OverallConfig.json 缺少 store_dir')
    if 'store_dir_structure' not in data:
        raise KeyError('OverallConfig.json 缺少 store_dir_structure')
    if 'window' not in data:
        raise KeyError('OverallConfig.json 缺少 window')
    return data


def build_store_paths(agent_id: str, config: dict | None = None) -> dict:
    """按 OverallConfig.json 组装 store/staging 的逻辑路径。"""
    cfg = config or load_overall_config()
    store_root = os.path.expanduser(cfg.get('store_dir', ''))
    s = cfg.get('store_dir_structure', {}) if isinstance(cfg.get('store_dir_structure'), dict) else {}
    mem = s.get('memory', {}) if isinstance(s.get('memory'), dict) else {}
    stg = s.get('staging', {}) if isinstance(s.get('staging'), dict) else {}

    memory_root = os.path.join(store_root, mem.get('root'))
    memory_agent_root = os.path.join(memory_root, agent_id)
    memory_surface_root = os.path.join(memory_agent_root, mem.get('surface'))
    memory_shallow_root = os.path.join(memory_agent_root, mem.get('shallow'))
    memory_deep_root = os.path.join(memory_agent_root, mem.get('deep'))

    staging_root = os.path.join(store_root, stg.get('root'))
    staging_surface_root = os.path.join(staging_root, stg.get('staging_surface'))
    staging_surface_agent_root = os.path.join(staging_surface_root, agent_id)
    staging_shallow_root = os.path.join(staging_root, stg.get('staging_shallow'))
    staging_deep_root = os.path.join(staging_root, stg.get('staging_deep'))

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


def _window_cfg(cfg: dict) -> dict:
    window = cfg.get('window') if isinstance(cfg.get('window'), dict) else {}
    start = window.get('start') if isinstance(window.get('start'), dict) else {}
    end = window.get('end') if isinstance(window.get('end'), dict) else {}
    boundary = window.get('boundary') if isinstance(window.get('boundary'), dict) else {}
    if not (start and end and boundary):
        raise KeyError('OverallConfig.json 缺少 window.start / window.end / window.boundary')
    return {
        'tz_name': cfg.get('timezone', 'Europe/London'),
        'start_day_offset': int(start.get('day_offset')),
        'start_hour': int(start.get('hour')),
        'start_minute': int(start.get('minute')),
        'end_day_offset': int(end.get('day_offset')),
        'end_hour': int(end.get('hour')),
        'end_minute': int(end.get('minute')),
        'boundary_hour': int(boundary.get('hour')),
        'boundary_minute': int(boundary.get('minute')),
    }


def compute_window(target_date_str: str, config: dict | None = None):
    """把 YYYY-MM-DD 转成配置化的 UTC 窗口。"""
    cfg = config or load_overall_config()
    w = _window_cfg(cfg)
    local_tz = ZoneInfo(w['tz_name'])

    try:
        local_day = datetime.strptime(target_date_str, '%Y-%m-%d').replace(tzinfo=local_tz)
    except ValueError as e:
        raise ValueError(f'日期格式错误: {target_date_str}') from e

    start_day = local_day + timedelta(days=w['start_day_offset'])
    end_day = local_day + timedelta(days=w['end_day_offset'])

    window_start = start_day.replace(hour=w['start_hour'], minute=w['start_minute'], second=0, microsecond=0).astimezone(timezone.utc)
    window_end = end_day.replace(hour=w['end_hour'], minute=w['end_minute'], second=0, microsecond=0).astimezone(timezone.utc)
    return window_start, window_end
