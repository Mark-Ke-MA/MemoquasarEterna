#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Adapters.openclaw.openclaw_shared_funcs import LoadConfig, output_failure, output_success

MEMORY_WORKER_PLACEHOLDER = '{{MEMORY_WORKER_AGENT_ID}}'
STORE_DIR_PLACEHOLDER = '{{STORE_DIR}}'


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[5]


def _cfg(repo_root: str | Path | None = None) -> LoadConfig:
    return LoadConfig(Path(repo_root) if repo_root is not None else _repo_root_from_here())


def _template_root() -> Path:
    return Path(__file__).resolve().parent / 'workspace'


def _workspace_target_path(cfg: LoadConfig) -> Path:
    worker_agent_id = str(cfg.overall_config.get('memory_worker_agentId', '') or '').strip()
    if not worker_agent_id:
        raise KeyError('OverallConfig.json 缺少 memory_worker_agentId')
    template = str(cfg.openclaw_config.get('memory_worker_agent_workspace_path', '') or '').strip()
    if not template:
        raise KeyError('OpenclawConfig.json 缺少 memory_worker_agent_workspace_path')
    rendered = template.format(memory_worker_agentId=worker_agent_id)
    return Path(rendered).expanduser()


def _replace_placeholders(root: Path, *, worker_agent_id: str, store_dir: str) -> list[str]:
    touched: list[str] = []
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {'.md', '.txt', '.json', '.yaml', '.yml'}:
            continue
        text = path.read_text(encoding='utf-8')
        new_text = text.replace(MEMORY_WORKER_PLACEHOLDER, worker_agent_id)
        new_text = new_text.replace(STORE_DIR_PLACEHOLDER, store_dir)
        if new_text != text:
            path.write_text(new_text, encoding='utf-8')
            touched.append(str(path))
    return touched


def install_memory_worker_workspace(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict:
    cfg = _cfg(repo_root)
    template_root = _template_root()
    if not template_root.exists() or not template_root.is_dir():
        raise FileNotFoundError(f'workspace 模板目录不存在: {template_root}')

    worker_agent_id = str(cfg.overall_config.get('memory_worker_agentId', '') or '').strip()
    if not worker_agent_id:
        raise KeyError('OverallConfig.json 缺少 memory_worker_agentId')
    store_dir = str(cfg.overall_config.get('store_dir', '') or '').strip()
    if not store_dir:
        raise KeyError('OverallConfig.json 缺少 store_dir')

    target_root = _workspace_target_path(cfg)
    existed_before = target_root.exists()
    if dry_run:
        return {
            'success': True,
            'dry_run': True,
            'worker_agent_id': worker_agent_id,
            'store_dir': store_dir,
            'template_root': str(template_root),
            'target_root': str(target_root),
            'mode': 'would-overwrite' if existed_before else 'would-create',
        }

    if existed_before:
        shutil.rmtree(target_root)
    shutil.copytree(template_root, target_root)
    replaced_files = _replace_placeholders(target_root, worker_agent_id=worker_agent_id, store_dir=store_dir)

    return {
        'success': True,
        'dry_run': False,
        'worker_agent_id': worker_agent_id,
        'store_dir': store_dir,
        'template_root': str(template_root),
        'target_root': str(target_root),
        'mode': 'overwritten' if existed_before else 'created',
        'replaced_files': replaced_files,
        'files': sorted(str(path) for path in target_root.rglob('*') if path.is_file()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Install OpenClaw memory worker agent workspace from template')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--dry-run', action='store_true', help='只输出计划，不写文件')
    args = parser.parse_args()

    try:
        result = install_memory_worker_workspace(repo_root=args.repo_root, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        output_failure(str(exc))
    output_success(result)


if __name__ == '__main__':
    main()
