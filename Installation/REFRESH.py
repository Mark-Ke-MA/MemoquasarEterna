#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.shared_funcs import LoadConfig
from Installation.INSTALL import run_install as run_top_install
from Installation.UNINSTALL import run_uninstall as run_top_uninstall
from Installation.install_log_utils import load_latest_snapshot


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[1]


def _step_status_text(success: bool, warning_count: int) -> str:
    if success and warning_count > 0:
        return f'完成（{warning_count} 条 warning）'
    if success:
        return '完成'
    return '失败'


def _collect_messages(result: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    message = str(result.get('message', '') or '').strip()
    if message:
        messages.append(message)
    warnings = result.get('warnings')
    if isinstance(warnings, list):
        messages.extend(str(x) for x in warnings if str(x).strip())
    return messages


def _format_refresh_result(result: dict[str, Any]) -> str:
    lines: list[str] = []
    success = bool(result.get('success', False))
    dry_run = bool(result.get('dry_run', False))
    title = 'MemoquasarEterna refresh 完成。' if success else 'MemoquasarEterna refresh 失败。'
    if dry_run:
        title += '（dry-run）'
    lines.append(title)
    lines.append('')

    steps = result.get('steps') if isinstance(result.get('steps'), list) else []
    for idx, step in enumerate(steps, start=1):
        lines.append(f'[{idx}/{len(steps)}] {step.get("title", step.get("name", ""))}：{_step_status_text(bool(step.get("success", False)), int(step.get("warning_count", 0) or 0))}')

    if not success:
        failed_step = str(result.get('failed_step', '') or '').strip()
        if failed_step:
            lines.append('')
            lines.append(f'失败步骤：{failed_step}')

    messages = result.get('messages') if isinstance(result.get('messages'), list) else []
    if messages:
        lines.append('')
        lines.append('提示：' if success else '详情：')
        seen: set[str] = set()
        for item in messages:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            lines.append(f'- {text}')

    return '\n'.join(lines).rstrip() + '\n'


def _expand(path_value: str) -> Path:
    return Path(path_value).expanduser().resolve()


def _snapshot_old_dirs(snapshot: dict[str, Any] | None) -> tuple[Path | None, Path | None]:
    if not isinstance(snapshot, dict):
        return None, None
    resolved = snapshot.get('resolved') or {}
    if not isinstance(resolved, dict):
        return None, None
    store_dir = str(resolved.get('store_dir', '') or '').strip()
    archive_dir = str(resolved.get('archive_dir', '') or '').strip()
    return (_expand(store_dir) if store_dir else None, _expand(archive_dir) if archive_dir else None)


def _current_dirs(repo_root: Path) -> tuple[Path | None, Path | None]:
    cfg = LoadConfig(repo_root).overall_config
    store_dir = str(cfg.get('store_dir', '') or '').strip()
    archive_dir = str(cfg.get('archive_dir', '') or '').strip()
    return (_expand(store_dir) if store_dir else None, _expand(archive_dir) if archive_dir else None)


def _migrate_one_dir(*, label: str, old_path: Path | None, new_path: Path | None, dry_run: bool) -> tuple[bool, list[str], dict[str, Any]]:
    messages: list[str] = []
    if old_path is None or new_path is None:
        messages.append(f'{label}：snapshot 未记录旧路径或当前配置未提供新路径，已跳过迁移。')
        return True, messages, {'label': label, 'status': 'skipped', 'reason': 'path-missing'}
    if old_path == new_path:
        messages.append(f'{label}：旧路径与新路径一致，已跳过迁移。')
        return True, messages, {'label': label, 'status': 'skipped', 'reason': 'same-path', 'path': str(old_path)}
    if not old_path.exists():
        messages.append(f'{label}：未检测到旧路径 {old_path}，已跳过迁移。')
        return True, messages, {'label': label, 'status': 'skipped', 'reason': 'old-missing', 'old_path': str(old_path), 'new_path': str(new_path)}
    if new_path.exists():
        messages.append(f'{label}：目标新路径已存在 {new_path}，为避免混合数据，未自动迁移。')
        return False, messages, {'label': label, 'status': 'failed', 'reason': 'new-exists', 'old_path': str(old_path), 'new_path': str(new_path)}
    if dry_run:
        messages.append(f'{label}：将迁移 {old_path} -> {new_path}。')
        return True, messages, {'label': label, 'status': 'would-move', 'old_path': str(old_path), 'new_path': str(new_path)}
    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old_path), str(new_path))
    messages.append(f'{label}：已迁移 {old_path} -> {new_path}。')
    return True, messages, {'label': label, 'status': 'moved', 'old_path': str(old_path), 'new_path': str(new_path)}


def _run_dir_migration(*, repo_root: Path, snapshot: dict[str, Any] | None, dry_run: bool) -> dict[str, Any]:
    old_store, old_archive = _snapshot_old_dirs(snapshot)
    new_store, new_archive = _current_dirs(repo_root)

    success = True
    messages: list[str] = []
    details: list[dict[str, Any]] = []
    for label, old_path, new_path in (
        ('store_dir', old_store, new_store),
        ('archive_dir', old_archive, new_archive),
    ):
        step_success, step_messages, detail = _migrate_one_dir(label=label, old_path=old_path, new_path=new_path, dry_run=dry_run)
        success = success and step_success
        messages.extend(step_messages)
        details.append(detail)

    return {
        'success': success,
        'status': 'success' if success else 'failed',
        'dry_run': dry_run,
        'warnings': [] if success else messages,
        'details': details,
        'messages': messages,
    }


def run_refresh(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else _repo_root_from_here()
    snapshot, _snapshot_path = load_latest_snapshot(repo_root_path)
    steps: list[dict[str, Any]] = []
    messages: list[str] = []

    uninstall_result = run_top_uninstall(repo_root=repo_root_path, dry_run=dry_run, snapshot=snapshot, use_latest_snapshot=True)
    uninstall_warning_count = len(uninstall_result.get('warnings', [])) if isinstance(uninstall_result.get('warnings'), list) else 0
    steps.append({
        'name': 'uninstall',
        'title': 'Uninstall',
        'success': bool(uninstall_result.get('success', False)),
        'warning_count': uninstall_warning_count,
    })
    messages.extend(_collect_messages(uninstall_result))
    if not bool(uninstall_result.get('success', False)):
        return {
            'success': False,
            'status': 'failed',
            'dry_run': dry_run,
            'failed_step': 'Uninstall',
            'steps': steps,
            'messages': messages,
        }

    migration_result = _run_dir_migration(repo_root=repo_root_path, snapshot=snapshot, dry_run=dry_run)
    migration_warning_count = len(migration_result.get('warnings', [])) if isinstance(migration_result.get('warnings'), list) else 0
    steps.append({
        'name': 'migrate_dirs',
        'title': 'Migrate old dirs',
        'success': bool(migration_result.get('success', False)),
        'warning_count': migration_warning_count,
    })
    messages.extend(str(x) for x in migration_result.get('messages', []) if str(x).strip())
    if not bool(migration_result.get('success', False)):
        return {
            'success': False,
            'status': 'failed',
            'dry_run': dry_run,
            'failed_step': 'Migrate old dirs',
            'steps': steps,
            'messages': messages,
        }

    install_result = run_top_install(repo_root=repo_root_path, dry_run=dry_run, trigger='refresh')
    install_warning_count = len(install_result.get('warnings', [])) if isinstance(install_result.get('warnings'), list) else 0
    steps.append({
        'name': 'install',
        'title': 'Install',
        'success': bool(install_result.get('success', False)),
        'warning_count': install_warning_count,
    })
    messages.extend(_collect_messages(install_result))
    if not bool(install_result.get('success', False)):
        return {
            'success': False,
            'status': 'failed',
            'dry_run': dry_run,
            'failed_step': 'Install',
            'steps': steps,
            'messages': messages,
        }

    return {
        'success': True,
        'status': 'success_with_warnings' if messages else 'success',
        'dry_run': dry_run,
        'steps': steps,
        'messages': messages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Top-level refresh orchestrator')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--dry-run', action='store_true', help='只执行支持 dry-run 的步骤，不实际删除或安装')
    args = parser.parse_args()
    result = run_refresh(repo_root=args.repo_root, dry_run=args.dry_run)
    sys.stdout.write(_format_refresh_result(result))
    raise SystemExit(0 if bool(result.get('success', False)) else 1)


if __name__ == '__main__':
    main()
