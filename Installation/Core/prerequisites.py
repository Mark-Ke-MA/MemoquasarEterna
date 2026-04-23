#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.shared_funcs import LoadConfig, output_success, write_json_atomic


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def _cfg(repo_root: str | Path | None = None) -> LoadConfig:
    return LoadConfig(Path(repo_root) if repo_root is not None else _repo_root_from_here())


def _require_str(data: dict[str, Any], key: str, *, where: str, errors: list[str]) -> str:
    value = str(data.get(key, '') or '').strip()
    if not value:
        errors.append(f'{where} 缺少 {key}')
    return value


def _require_dict(data: dict[str, Any], key: str, *, where: str, errors: list[str]) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        errors.append(f'{where} 缺少 {key}')
        return {}
    return value


def _require_list(data: dict[str, Any], key: str, *, where: str, errors: list[str]) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        errors.append(f'{where} 缺少 {key} 或其为空')
        return []
    return value


def _check_hhmm(value: str, *, where: str, errors: list[str]) -> None:
    if not re.fullmatch(r'\d{2}:\d{2}', value):
        errors.append(f'{where} 必须是 HH:MM 格式')
        return
    hour, minute = map(int, value.split(':'))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        errors.append(f'{where} 超出合法范围，应为 00:00-23:59')


def _check_weekday(value: str, *, where: str, errors: list[str]) -> None:
    allowed = {'sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'}
    if str(value or '').strip()[:3].lower() not in allowed:
        errors.append(f'{where} 必须是 Sun/Mon/.../Sat')


def _check_parent_writable(path_value: str, *, label: str, warnings: list[str]) -> None:
    expanded = Path(os.path.expanduser(path_value))
    parent = expanded.parent
    if parent.exists():
        if not os.access(parent, os.W_OK):
            warnings.append(f'{label} 的父目录当前不可写：{parent}')
        return
    probe = parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not os.access(probe, os.W_OK):
        warnings.append(f'{label} 的上级目录当前不可写：{probe}')


def _check_python(checks: dict[str, Any], errors: list[str]) -> None:
    version_info = sys.version_info
    checks['python'] = {
        'status': 'ok' if version_info >= (3, 10) else 'failed',
        'executable': sys.executable,
        'version': f'{version_info.major}.{version_info.minor}.{version_info.micro}',
    }
    if version_info < (3, 10):
        errors.append('Python 版本过低；要求至少 3.10')


def _check_crontab(checks: dict[str, Any], errors: list[str]) -> None:
    path = shutil.which('crontab')
    checks['crontab'] = {
        'status': 'ok' if path else 'failed',
        'path': path,
    }
    if not path:
        errors.append('找不到 crontab 命令，无法安装 core auto cron')


def _check_embedding(cfg: dict[str, Any], checks: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    use_embedding = bool(cfg.get('use_embedding', False))
    if not use_embedding:
        checks['embedding'] = {
            'status': 'skipped',
            'reason': 'use_embedding=false',
        }
        return

    url = str(cfg.get('embedding_api_url', '') or '').strip()
    model = str(cfg.get('embedding_model', '') or '').strip()
    if not url:
        errors.append('OverallConfig.json.use_embedding=true 时，embedding_api_url 不能为空')
        checks['embedding'] = {'status': 'failed', 'url': url, 'model': model}
        return
    if not model:
        errors.append('OverallConfig.json.use_embedding=true 时，embedding_model 不能为空')
        checks['embedding'] = {'status': 'failed', 'url': url, 'model': model}
        return

    payload = json.dumps({'model': model, 'input': 'ping'}).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            ok = 200 <= resp.status < 300
            checks['embedding'] = {
                'status': 'ok' if ok else 'failed',
                'url': url,
                'model': model,
                'http_status': resp.status,
            }
            if not ok:
                errors.append(f'embedding_api_url 返回非成功状态码: {resp.status}')
            elif not body.strip():
                warnings.append('embedding_api_url 返回空响应，请确认 embeddings 服务是否正常')
    except urllib.error.URLError as exc:
        checks['embedding'] = {
            'status': 'failed',
            'url': url,
            'model': model,
            'error': str(exc),
        }
        errors.append(f'无法连接 embedding_api_url: {exc}')


def _maybe_fix_code_dir(cfg: dict[str, Any], *, repo_root: Path, dry_run: bool, warnings: list[str]) -> tuple[dict[str, Any], str, str, bool]:
    current = str(cfg.get('code_dir', '') or '').strip()
    repo_root_resolved = repo_root.resolve()
    current_resolved = Path(os.path.expanduser(current)).resolve() if current else None
    if current and current_resolved == repo_root_resolved:
        return cfg, str(current_resolved), str(repo_root_resolved), False

    updated = dict(cfg)
    updated['code_dir'] = str(repo_root_resolved)
    if not dry_run:
        write_json_atomic(repo_root / 'OverallConfig.json', updated, indent=2)
    warnings.append('初始 code_dir 与真实 repo_root 不一致，已自动修复为当前仓库路径。')
    return updated, str(current_resolved) if current_resolved else '', str(repo_root_resolved), True


def _check_config(cfg: dict[str, Any], *, repo_root: Path, dry_run: bool, checks: dict[str, Any], errors: list[str], warnings: list[str]) -> dict[str, Any]:
    product_name = _require_str(cfg, 'product_name', where='OverallConfig.json', errors=errors)
    harness = _require_str(cfg, 'harness', where='OverallConfig.json', errors=errors)
    memory_worker_agent_id = _require_str(cfg, 'memory_worker_agentId', where='OverallConfig.json', errors=errors)
    agent_ids_raw = _require_list(cfg, 'agentId_list', where='OverallConfig.json', errors=errors)
    agent_ids = [str(x).strip() for x in agent_ids_raw if str(x).strip()]
    if not agent_ids:
        errors.append('OverallConfig.json.agentId_list 解析后为空')

    code_dir = _require_str(cfg, 'code_dir', where='OverallConfig.json', errors=errors)
    store_dir = _require_str(cfg, 'store_dir', where='OverallConfig.json', errors=errors)
    archive_dir = _require_str(cfg, 'archive_dir', where='OverallConfig.json', errors=errors)
    layer1_marker = _require_str(cfg, 'layer1_auto_cron_marker', where='OverallConfig.json', errors=errors)
    layer3_marker = _require_str(cfg, 'layer3_auto_cron_marker', where='OverallConfig.json', errors=errors)
    daily_write_cron_time = _require_str(cfg, 'daily_write_cron_time', where='OverallConfig.json', errors=errors)
    weekly_decay_cron_day = _require_str(cfg, 'weekly_decay_cron_day', where='OverallConfig.json', errors=errors)
    weekly_decay_cron_time = _require_str(cfg, 'weekly_decay_cron_time', where='OverallConfig.json', errors=errors)
    timezone = _require_str(cfg, 'timezone', where='OverallConfig.json', errors=errors)

    _check_hhmm(daily_write_cron_time, where='OverallConfig.json.daily_write_cron_time', errors=errors)
    _check_hhmm(weekly_decay_cron_time, where='OverallConfig.json.weekly_decay_cron_time', errors=errors)
    _check_weekday(weekly_decay_cron_day, where='OverallConfig.json.weekly_decay_cron_day', errors=errors)

    if memory_worker_agent_id and memory_worker_agent_id in agent_ids:
        errors.append('OverallConfig.json.memory_worker_agentId 不允许出现在 agentId_list 中')

    if len(agent_ids) != len(set(agent_ids)):
        errors.append('OverallConfig.json.agentId_list 中存在重复项')

    cfg, code_dir_initial, code_dir_effective, code_dir_auto_fixed = _maybe_fix_code_dir(
        cfg,
        repo_root=repo_root,
        dry_run=dry_run,
        warnings=warnings,
    )

    _check_parent_writable(store_dir, label='OverallConfig.json.store_dir', warnings=warnings)
    _check_parent_writable(archive_dir, label='OverallConfig.json.archive_dir', warnings=warnings)

    if not isinstance(cfg.get('nprl_llm_max'), int) or int(cfg.get('nprl_llm_max', 0)) <= 0:
        errors.append('OverallConfig.json.nprl_llm_max 必须是正整数')

    _require_dict(cfg, 'window', where='OverallConfig.json', errors=errors)
    _require_dict(cfg, 'layer1_write', where='OverallConfig.json', errors=errors)
    _require_dict(cfg, 'layer3_decay', where='OverallConfig.json', errors=errors)
    _require_dict(cfg, 'archive_dir_structure', where='OverallConfig.json', errors=errors)
    _require_dict(cfg, 'store_dir_structure', where='OverallConfig.json', errors=errors)

    checks['config'] = {
        'status': 'ok',
        'product_name': product_name,
        'harness': harness,
        'timezone': timezone,
        'agent_count': len(agent_ids),
        'memory_worker_agentId': memory_worker_agent_id,
        'code_dir_initial': code_dir_initial,
        'code_dir_effective': code_dir_effective,
        'code_dir_auto_fixed': code_dir_auto_fixed,
        'store_dir': str(Path(os.path.expanduser(store_dir)).resolve()) if store_dir else '',
        'archive_dir': str(Path(os.path.expanduser(archive_dir)).resolve()) if archive_dir else '',
        'layer1_auto_cron_marker': layer1_marker,
        'layer3_auto_cron_marker': layer3_marker,
    }

    return cfg


def run_prerequisites(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else _repo_root_from_here()
    checks: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []

    try:
        cfg = _cfg(repo_root_path).overall_config
    except Exception as exc:
        return {
            'success': False,
            'status': 'failed',
            'dry_run': dry_run,
            'errors': [str(exc)],
            'warnings': [],
            'checks': checks,
        }

    cfg = _check_config(cfg, repo_root=repo_root_path, dry_run=dry_run, checks=checks, errors=errors, warnings=warnings)
    _check_python(checks, errors)
    _check_crontab(checks, errors)
    _check_embedding(cfg, checks, errors, warnings)

    if errors:
        if 'config' in checks:
            checks['config']['status'] = 'failed'
        return {
            'success': False,
            'status': 'failed',
            'dry_run': dry_run,
            'errors': errors,
            'warnings': warnings,
            'checks': checks,
        }

    return {
        'success': True,
        'status': 'success_with_warnings' if warnings else 'success',
        'dry_run': dry_run,
        'errors': [],
        'warnings': warnings,
        'checks': checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Core installation prerequisites check.')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--dry-run', action='store_true', help='仅执行预检；该脚本本身不会写入任何内容')
    args = parser.parse_args()
    output_success(run_prerequisites(repo_root=args.repo_root, dry_run=args.dry_run))


if __name__ == '__main__':
    main()
