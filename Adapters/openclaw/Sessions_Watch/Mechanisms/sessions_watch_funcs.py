#!/usr/bin/env python3
"""OpenClaw sessions-watch pure helpers.

只保留纯函数/纯规则：
- known-direct-sessions.json 的基础读写与幂等更新
- session_watch 初始化所需的 label / path / plist 生成

这个模块不承担顶层命令编排；顶层管理动作放在 `sessions_watch_manage.py`。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from Adapters.openclaw.openclaw_shared_funcs import LoadConfig


def normalize_known_sessions(data: dict | None) -> dict:
    if not isinstance(data, dict):
        data = {}
    history = data.get("history_sessions")
    if not isinstance(history, list):
        history = []
    return {"history_sessions": history}


def load_known_sessions(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {"history_sessions": []}
    try:
        with open(path, encoding="utf-8") as f:
            return normalize_known_sessions(json.load(f))
    except Exception:
        return {"history_sessions": []}


def save_known_sessions(path: str, data: dict, *, dry_run: bool = False) -> str:
    normalized = normalize_known_sessions(data)
    if dry_run:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return path


def upsert_known_session(
    data: dict,
    *,
    date: str,
    session_id: str,
    first_seen: str,
) -> dict:
    """把一个 sessionId 追加到某个 date 条目里，保持幂等。"""
    normalized = normalize_known_sessions(data)
    history = normalized["history_sessions"]
    date_entry = next((entry for entry in history if entry.get("date") == date), None)
    if date_entry is None:
        date_entry = {"date": date, "sessions": []}
        history.append(date_entry)

    sessions = date_entry.setdefault("sessions", [])
    if not any(item.get("sessionId") == session_id for item in sessions if isinstance(item, dict)):
        sessions.append({"sessionId": session_id, "first_seen": first_seen})
    return normalized


def _load_cfg(repo_root: str | Path | None = None) -> LoadConfig:
    return LoadConfig(repo_root)


def build_session_watch_label(
    agent_id: str,
    *,
    suffix: str | int | None = "1",
    label_prefix: str | None = None,
    repo_root: str | Path | None = None,
) -> str:
    cfg = _load_cfg(repo_root)
    prefix = label_prefix or cfg.openclaw_config["maintenance"]["plist_label_prefix"]
    if suffix is None:
        return f"{prefix}.{agent_id}"
    return f"{prefix}.{agent_id}.{suffix}"


def split_session_watch_label(label: str, *, label_prefix: str | None = None, repo_root: str | Path | None = None) -> dict:
    cfg = _load_cfg(repo_root)
    prefix = label_prefix or cfg.openclaw_config["maintenance"]["plist_label_prefix"]
    head = f"{prefix}."
    if not label.startswith(head):
        raise ValueError(f"label 不符合 session-watch 前缀: {label}")
    remainder = label[len(head):]
    parts = remainder.rsplit('.', 1)
    if len(parts) == 2:
        agent_id, suffix_text = parts
        suffix: str | int | None = int(suffix_text) if suffix_text.isdigit() else suffix_text
    else:
        agent_id = remainder
        suffix = None
    return {
        "label_prefix": prefix,
        "agent_id": agent_id,
        "suffix": suffix,
        "label": label,
    }


def build_openclaw_paths(
    agent_id: str,
    *,
    repo_root: str | Path | None = None,
    label: str | None = None,
    suffix: str | int | None = "1",
) -> dict[str, str]:
    cfg = _load_cfg(repo_root)
    maintenance = cfg.openclaw_config["maintenance"]
    adapter_dirname = str(cfg.openclaw_config.get("adapter_dirname", Path(__file__).resolve().parents[2].name) or Path(__file__).resolve().parents[2].name)
    sessions_path = os.path.expanduser(cfg.openclaw_config["sessions_path"].format(
        agentId=agent_id,
        agent_id=agent_id,
        code_dir=cfg.code_root,
        adapter_dirname=adapter_dirname,
    ))
    sessions_json_path = os.path.join(sessions_path, "sessions.json")
    sessions_registry_path = os.path.expanduser(cfg.openclaw_config["sessions_registry_path"].format(
        agentId=agent_id,
        agent_id=agent_id,
        code_dir=cfg.code_root,
        adapter_dirname=adapter_dirname,
    ))
    watch_script_path = os.path.join(cfg.code_root, "Adapters", adapter_dirname, "Sessions_Watch", "Mechanisms", "sessions_watch_runtime.py")
    launch_agents_dir = os.path.expanduser(maintenance["launch_agents_dir"])
    log_base_dir = os.path.expanduser(maintenance["log_base_dir"].format(store_dir=cfg.store_root))
    resolved_label = label or build_session_watch_label(agent_id, suffix=suffix, repo_root=repo_root)
    plist_path = os.path.join(launch_agents_dir, f"{resolved_label}.plist")
    return {
        "agent_id": agent_id,
        "code_dir": cfg.code_root,
        "sessions_path": sessions_path,
        "sessions_index": sessions_path,
        "sessions_json_path": sessions_json_path,
        "sessions_registry_path": sessions_registry_path,
        "known_sessions_path": sessions_registry_path,
        "watch_script_path": watch_script_path,
        "launch_agents_dir": launch_agents_dir,
        "plist_label": resolved_label,
        "plist_path": plist_path,
        "log_base_dir": log_base_dir,
        "log_out": os.path.join(log_base_dir, f"session_watch_{agent_id}.log"),
        "log_err": os.path.join(log_base_dir, f"session_watch_{agent_id}_err.log"),
    }


def build_session_watch_plist(
    *,
    agent_id: str,
    watch_script_path: str,
    sessions_index: str,
    log_out: str,
    log_err: str,
    label: str | None = None,
    label_prefix: str | None = None,
    suffix: str | int | None = "1",
    repo_root: str | Path | None = None,
    python_executable: str | None = None,
) -> str:
    python_executable = python_executable or sys.executable
    if label is None:
        label = build_session_watch_label(agent_id, suffix=suffix, label_prefix=label_prefix, repo_root=repo_root)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python_executable}</string>
        <string>{watch_script_path}</string>
        <string>--agent</string>
        <string>{agent_id}</string>
        <string>--sessions-index</string>
        <string>{sessions_index}</string>
    </array>

    <key>WatchPaths</key>
    <array>
        <string>{sessions_index}</string>
    </array>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>{log_out}</string>

    <key>StandardErrorPath</key>
    <string>{log_err}</string>
</dict>
</plist>
"""


def build_initialize_plan(
    agent_id: str,
    *,
    repo_root: str | Path | None = None,
    label: str | None = None,
    suffix: str | int | None = "1",
) -> dict:
    cfg = _load_cfg(repo_root)
    adapter_dirname = str(cfg.openclaw_config.get("adapter_dirname", Path(__file__).resolve().parents[2].name) or Path(__file__).resolve().parents[2].name)
    paths = build_openclaw_paths(agent_id, repo_root=repo_root, label=label, suffix=suffix)
    plist_content = build_session_watch_plist(
        agent_id=agent_id,
        watch_script_path=paths["watch_script_path"],
        sessions_index=paths["sessions_index"],
        log_out=paths["log_out"],
        log_err=paths["log_err"],
        label=paths["plist_label"],
        repo_root=repo_root,
    )
    return {
        "agent_id": agent_id,
        "repo_root": str(Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[4]),
        "overall_config_path": str((Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[4]) / "OverallConfig.json"),
        "openclaw_config_path": str((Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[4]) / "Adapters" / adapter_dirname / "OpenclawConfig.json"),
        "paths": paths,
        "label": paths["plist_label"],
        "suffix": split_session_watch_label(paths["plist_label"], repo_root=repo_root)["suffix"],
        "known_sessions_seed": load_known_sessions(paths["known_sessions_path"]),
        "plist_content": plist_content,
    }
