#!/usr/bin/env python3
"""OpenClaw sessions-watch runtime hook.

这个脚本由 launchd 的 WatchPaths 触发，用于：
- 读取 OpenClaw 当前 direct session
- 计算当天窗口日期（03:00 边界）
- 更新 known-direct-sessions.json

它是 runtime payload，不负责初始化安装，也不执行 launchctl。
它只依赖 `openclaw_Maintenance/` 的基础读写能力，与初始化入口并列，不互相调用。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Adapters.openclaw.Sessions_Watch.Mechanisms.sessions_watch_funcs import build_openclaw_paths, load_known_sessions, save_known_sessions, upsert_known_session
from Adapters.openclaw.openclaw_shared_funcs import dbg, get_window_date, LoadConfig, SessionFinder
from Core.shared_funcs import get_production_agents


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[4]


def _append_or_keep_known_session(known_path: str, date: str, session_id: str, first_seen: str, *, dry_run: bool) -> dict:
    data = load_known_sessions(known_path)
    updated = upsert_known_session(data, date=date, session_id=session_id, first_seen=first_seen)
    if not dry_run:
        save_known_sessions(known_path, updated)
    return updated


def run_for_agent(
    agent_id: str,
    *,
    sessions_index: str | None = None,
    known_sessions_path: str | None = None,
    dry_run: bool = False,
    repo_root: str | Path | None = None,
) -> dict:
    repo_root = Path(repo_root) if repo_root is not None else _repo_root_from_here()
    paths = build_openclaw_paths(agent_id, repo_root=repo_root)

    sessions_index = sessions_index or paths["sessions_index"]
    known_sessions_path = known_sessions_path or paths["known_sessions_path"]

    current_session_id = SessionFinder(repo_root, agentId=agent_id).find_current_session_id()
    if not current_session_id:
        return {
            "agent": agent_id,
            "skipped": True,
            "reason": "no current session",
            "sessions_index": sessions_index,
            "known_sessions_path": known_sessions_path,
        }

    window_date = get_window_date(repo_root)
    first_seen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    before = load_known_sessions(known_sessions_path)
    after = _append_or_keep_known_session(known_sessions_path, window_date, current_session_id, first_seen, dry_run=dry_run)

    changed = before != after
    dbg(f"[{agent_id}] window_date={window_date}, sessionId={current_session_id[:8]}, changed={changed}, dry_run={dry_run}")

    return {
        "agent": agent_id,
        "date": window_date,
        "session_id": current_session_id,
        "sessions_index": sessions_index,
        "known_sessions_path": known_sessions_path,
        "changed": changed,
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClaw session registry runtime hook")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--agent", help="处理单个 agent")
    group.add_argument("--all", action="store_true", help="处理全部 agent（从 OverallConfig 读取）")
    parser.add_argument("--sessions-index", default=None, help="手动指定 sessions.json 路径（调试用）")
    parser.add_argument("--known-sessions-path", default=None, help="手动指定 known-direct-sessions.json 路径（调试用）")
    parser.add_argument("--dry-run", action="store_true", help="只计算，不写文件")
    parser.add_argument("--repo-root", default=None, help="仓库根目录（默认自动推断）")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else _repo_root_from_here()
    overall_config = LoadConfig(repo_root).overall_config
    agents = [item['agentId'] for item in get_production_agents(overall_config) if item['harness'] == 'openclaw']

    targets = agents if args.all else [args.agent]
    results = [
        run_for_agent(
            agent_id,
            sessions_index=args.sessions_index,
            known_sessions_path=args.known_sessions_path,
            dry_run=args.dry_run,
            repo_root=repo_root,
        )
        for agent_id in targets
    ]

    print(json.dumps({"success": True, "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
