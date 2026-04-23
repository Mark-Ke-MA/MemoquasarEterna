#!/usr/bin/env python3
"""OpenClaw shared function pool.

只保留最小公共面：
- dbg
- output_success
- output_failure
- LoadConfig
- SessionFinder
- get_window_date
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


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


class LoadConfig:
    def __init__(self, repo_root: str | Path | None = None):
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
        self.adapter_root = Path(__file__).resolve().parent
        self.overall_config = self.load_overall_config()
        self.openclaw_config = self.load_openclaw_config()
        self.code_root = os.path.expanduser(self.overall_config['code_dir'])
        self.store_root = os.path.expanduser(self.overall_config['store_dir'])

    def load_json_file(self, path: str) -> dict:
        with open(path, encoding='utf-8') as f:
            return json.load(f)

    def load_overall_config(self) -> dict:
        path = self.repo_root / 'OverallConfig.json'
        return self.load_json_file(str(path))

    def load_openclaw_config(self) -> dict:
        path = self.adapter_root / 'OpenclawConfig.json'
        data = self.load_json_file(str(path))
        if not isinstance(data, dict):
            raise ValueError(f'OpenclawConfig.json 格式错误: {path}')
        data.setdefault('adapter_dirname', self.adapter_root.name)
        return data


class SessionFinder:
    def __init__(self, repo_root: str | Path | None = None, agentId: str = None):
        self.agent_id = agentId
        self.Config = LoadConfig(repo_root=repo_root)

    def _render_channel_template(self) -> str:
        rules = self.Config.openclaw_config['sessions_registry_maintenance']
        required = ('key_template',)
        for key in required:
            if key not in rules:
                raise KeyError(f'OpenclawConfig.json.sessions_registry_maintenance 缺少 {key}')
        return rules['key_template'].format(agentId=self.agent_id)

    def find_current_session_id(self) -> str:
        sessions_path = self.Config.openclaw_config['sessions_path'].format(
            agentId=self.agent_id,
            agent_id=self.agent_id,
            code_dir=self.Config.code_root,
            adapter_dirname=self.Config.openclaw_config.get('adapter_dirname', self.Config.adapter_root.name),
        )
        sessions_json_path = os.path.join(os.path.expanduser(sessions_path), 'sessions.json')
        if not os.path.exists(sessions_json_path):
            dbg(f"sessions.json 不存在: {sessions_json_path}")
            return None
        with open(sessions_json_path, encoding='utf-8') as f:
            sessions_data = json.load(f)
        session_id_field = self.Config.openclaw_config['sessions_registry_maintenance']['session_id_field']
        channel_key = self._render_channel_template()
        entry = sessions_data.get(channel_key)
        if not entry:
            dbg(f"sessions.json 中不存在 key: {channel_key}")
            return None
        session_id = entry.get(session_id_field)
        if not session_id:
            dbg(f"key {channel_key} 下无 {session_id_field}")
            return None
        dbg(f'找到 direct session: uuid={session_id[:8]}')
        return session_id


def get_window_date(repo_root: str | Path | None = None) -> str:
    cfg = LoadConfig(repo_root)
    local_tz = ZoneInfo(cfg.overall_config.get('timezone', 'Europe/London'))
    boundary = cfg.overall_config.get('window', {}).get('boundary', {})
    boundary_hour = int(boundary['hour'])
    boundary_minute = int(boundary['minute'])

    now_local = datetime.now(local_tz)
    boundary_now = now_local.replace(hour=boundary_hour, minute=boundary_minute, second=0, microsecond=0)
    if now_local < boundary_now:
        return (now_local - timedelta(days=1)).strftime('%Y-%m-%d')
    return now_local.strftime('%Y-%m-%d')
