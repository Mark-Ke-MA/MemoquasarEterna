#!/usr/bin/env python3
"""OpenClaw sessions-watch maintenance top-level.

这个入口只管理 watch plist 配置：
- list：列出现有 watch plist
- update：按指定 label 重写某个 watch plist
- delete：按指定 label 删除某个 watch plist；或 `--all` 批量删除所有 agent 对应的 watch plist

它只处理 launchd 任务，不动 Registries，也不动 sessions.json。
它可以依赖 `openclaw_shared_funcs.py` 与 `sessions_watch_funcs.py`，
但不应被 install/runtime 调用，也不应调用 install/runtime。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Adapters.openclaw.openclaw_shared_funcs import LoadConfig, dbg, output_failure
from Adapters.openclaw.Sessions_Watch.Mechanisms.sessions_watch_funcs import build_openclaw_paths, build_session_watch_plist, build_session_watch_label, split_session_watch_label


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[4]


def _cfg(repo_root: str | Path | None = None) -> LoadConfig:
    return LoadConfig(Path(repo_root) if repo_root is not None else _repo_root_from_here())


def _uid() -> int:
    return os.getuid()


def _launchctl(action: str, target: str) -> dict:
    cmd = ["launchctl", action, "-w", target]
    dbg(f"run: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "cmd": cmd,
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }


def _is_loaded(label: str) -> bool:
    result = subprocess.run(["launchctl", "print", f"gui/{_uid()}/{label}"], capture_output=True, text=True)
    return result.returncode == 0


def _write_text(path: str, content: str, *, dry_run: bool = False) -> str:
    if dry_run:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


def _crontab_list() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout or ""


def _crontab_write(content: str) -> dict:
    proc = subprocess.run(["crontab", "-"], input=content, capture_output=True, text=True)
    return {
        "cmd": ["crontab", "-"],
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def _remove_daily_cron(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict:
    current = _crontab_list()
    current_lines = [ln.rstrip() for ln in current.splitlines() if ln.strip()]
    cfg = _cfg(repo_root)
    marker = str(cfg.openclaw_config['maintenance']['daily_init_cron_marker'])
    begin_marker = f"# BEGIN {marker}"
    end_marker = f"# END {marker}"
    removed: list[str] = []
    kept: list[str] = []
    inside_block = False
    pending_title_idx: int | None = None
    for ln in current_lines:
        if ln.startswith('# ====='):
            pending_title_idx = len(kept)
            kept.append(ln)
            continue
        if ln == begin_marker:
            inside_block = True
            if pending_title_idx is not None and pending_title_idx == len(kept) - 1:
                removed.append(kept.pop())
            pending_title_idx = None
            removed.append(ln)
            continue
        if ln == end_marker:
            inside_block = False
            removed.append(ln)
            pending_title_idx = None
            continue
        if inside_block:
            removed.append(ln)
            continue
        pending_title_idx = None
        kept.append(ln)
    if not removed:
        return {
            "changed": False,
            "dry_run": dry_run,
            "status": "absent",
        }
    new_content = "\n".join(kept).strip()
    if new_content:
        new_content += "\n"
    if dry_run:
        return {
            "changed": True,
            "dry_run": True,
            "status": "would-remove",
            "removed": removed,
        }
    result = _crontab_write(new_content)
    if result["returncode"] != 0:
        output_failure(f"删除 00:01 cron 失败: {result['stderr'] or result['stdout']}")
    return {
        "changed": True,
        "dry_run": False,
        "status": "removed",
        "removed": removed,
        "crontab_write": result,
    }


def list_plists(*, repo_root: str | Path | None = None, label_prefix: str | None = None) -> list[dict]:
    cfg = _cfg(repo_root)
    maintenance = cfg.openclaw_config['maintenance']
    launch_agents_dir = os.path.expanduser(maintenance['launch_agents_dir'])
    prefix = label_prefix or maintenance['plist_label_prefix']
    if not os.path.isdir(launch_agents_dir):
        return []
    results: list[dict] = []
    for fname in sorted(os.listdir(launch_agents_dir)):
        if not (fname.startswith(prefix) and fname.endswith('.plist')):
            continue
        label = fname[:-6]
        results.append({
            'label': label,
            'path': os.path.join(launch_agents_dir, fname),
            'loaded': _is_loaded(label),
        })
    return results


def update_plist(label: str, *, repo_root: str | Path | None = None, dry_run: bool = False) -> dict:
    parsed = split_session_watch_label(label, repo_root=repo_root)
    paths = build_openclaw_paths(parsed['agent_id'], repo_root=repo_root, label=label)
    plist_content = build_session_watch_plist(
        agent_id=parsed['agent_id'],
        watch_script_path=paths['watch_script_path'],
        sessions_index=paths['sessions_index'],
        log_out=paths['log_out'],
        log_err=paths['log_err'],
        label=label,
        repo_root=repo_root,
    )
    if dry_run:
        return {
            'success': True,
            'dry_run': True,
            'label': label,
            'agent_id': parsed['agent_id'],
            'plist_path': paths['plist_path'],
            'unload': {'skipped': True},
            'load': {'skipped': True},
        }
    unload_result = _launchctl('unload', paths['plist_path'])
    _write_text(paths['plist_path'], plist_content, dry_run=False)
    load_result = _launchctl('load', paths['plist_path'])
    success = load_result['returncode'] == 0
    return {
        'success': success,
        'dry_run': False,
        'label': label,
        'agent_id': parsed['agent_id'],
        'plist_path': paths['plist_path'],
        'unload': unload_result,
        'load': load_result,
    }


def delete_plist(label: str, *, repo_root: str | Path | None = None, dry_run: bool = False) -> dict:
    parsed = split_session_watch_label(label, repo_root=repo_root)
    paths = build_openclaw_paths(parsed['agent_id'], repo_root=repo_root, label=label)
    if dry_run:
        return {
            'success': True,
            'dry_run': True,
            'label': label,
            'agent_id': parsed['agent_id'],
            'plist_path': paths['plist_path'],
            'unload': {'skipped': True},
        }
    unload_result = _launchctl('unload', paths['plist_path'])
    if os.path.exists(paths['plist_path']):
        os.remove(paths['plist_path'])
    return {
        'success': True,
        'dry_run': False,
        'label': label,
        'agent_id': parsed['agent_id'],
        'plist_path': paths['plist_path'],
        'unload': unload_result,
    }


def delete_all_plists(*, repo_root: str | Path | None = None, label_suffix: str | int | None = None, dry_run: bool = False, remove_daily_init_cron: bool = False) -> dict:
    cfg = _cfg(repo_root)
    agent_ids = cfg.overall_config['agentId_list']
    label_prefix = cfg.openclaw_config['maintenance']['plist_label_prefix']
    labels = [build_session_watch_label(agent_id, suffix=label_suffix, label_prefix=label_prefix, repo_root=repo_root) for agent_id in agent_ids]

    results = []
    for label in labels:
        paths = build_openclaw_paths(split_session_watch_label(label, repo_root=repo_root)['agent_id'], repo_root=repo_root, label=label)
        if dry_run:
            results.append({
                'success': True,
                'dry_run': True,
                'label': label,
                'plist_path': paths['plist_path'],
                'unload': {'skipped': True},
                'deleted': False,
            })
            continue
        unload_result = _launchctl('unload', paths['plist_path'])
        deleted = False
        if os.path.exists(paths['plist_path']):
            os.remove(paths['plist_path'])
            deleted = True
        results.append({
            'success': True,
            'dry_run': False,
            'label': label,
            'plist_path': paths['plist_path'],
            'unload': unload_result,
            'deleted': deleted,
        })

    cron_result = _remove_daily_cron(repo_root=repo_root, dry_run=dry_run) if remove_daily_init_cron else {'changed': False, 'dry_run': dry_run, 'status': 'skipped'}
    return {
        'success': True,
        'dry_run': dry_run,
        'mode': 'all',
        'labels': labels,
        'results': results,
        'cron_cleanup': cron_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='OpenClaw sessions-watch maintenance')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_list = sub.add_parser('list')
    p_list.add_argument('--label-prefix', default=None)
    p_list.add_argument('--repo-root', default=None)

    p_update = sub.add_parser('update')
    p_update.add_argument('--label', required=True)
    p_update.add_argument('--repo-root', default=None)
    p_update.add_argument('--dry-run', action='store_true')

    p_delete = sub.add_parser('delete')
    p_delete_group = p_delete.add_mutually_exclusive_group(required=True)
    p_delete_group.add_argument('--label', help='要删除的完整 plist label')
    p_delete_group.add_argument('--all', action='store_true', help='按当前配置批量删除所有 agent 的 watch plist')
    p_delete.add_argument('--label-suffix', default=None, help='--all 时用于推导 label 的 suffix；默认先不带 suffix')
    p_delete.add_argument('--remove-daily-init-cron', action='store_true', help='删除时同时清理 daily init cron')
    p_delete.add_argument('--repo-root', default=None)
    p_delete.add_argument('--dry-run', action='store_true')

    args = parser.parse_args()

    if args.cmd == 'list':
        print(json.dumps({'success': True, 'plists': list_plists(repo_root=args.repo_root, label_prefix=args.label_prefix)}, ensure_ascii=False, indent=2))
        return

    if args.cmd == 'update':
        print(json.dumps(update_plist(args.label, repo_root=args.repo_root, dry_run=args.dry_run), ensure_ascii=False, indent=2))
        return

    if args.cmd == 'delete':
        if args.all:
            print(json.dumps(delete_all_plists(repo_root=args.repo_root, label_suffix=args.label_suffix, dry_run=args.dry_run, remove_daily_init_cron=args.remove_daily_init_cron), ensure_ascii=False, indent=2))
            return
        delete_result = delete_plist(args.label, repo_root=args.repo_root, dry_run=args.dry_run)
        if args.remove_daily_init_cron:
            delete_result['cron_cleanup'] = _remove_daily_cron(repo_root=args.repo_root, dry_run=args.dry_run)
        print(json.dumps(delete_result, ensure_ascii=False, indent=2))
        return

    output_failure(f'unknown cmd: {args.cmd}')


if __name__ == '__main__':
    main()
