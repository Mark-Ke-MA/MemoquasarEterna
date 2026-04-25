#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ConfigSpec:
    key: str
    label: str
    config_relpath: Path
    template_relpath: Path


CONFIG_SPECS = (
    ConfigSpec(
        key='overall',
        label='OverallConfig.json',
        config_relpath=Path('OverallConfig.json'),
        template_relpath=Path('OverallConfig-template.json'),
    ),
)


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise ValueError(f'{label} 格式错误: {path}') from exc
    if not isinstance(data, dict):
        raise ValueError(f'{label} 必须是 JSON object: {path}')
    return data


def _schema_version(data: dict[str, Any], *, label: str) -> str:
    version = str(data.get('schema_version', '') or '').strip()
    if not version:
        raise KeyError(f'{label} 缺少 schema_version')
    return version


def ensure_config_file(repo_root: str | Path, spec: ConfigSpec, *, dry_run: bool = False) -> dict[str, Any]:
    repo_root = Path(repo_root)
    config_path = repo_root / spec.config_relpath
    template_path = repo_root / spec.template_relpath

    if not template_path.exists():
        return {
            'success': False,
            'status': 'missing_template',
            'config': str(config_path),
            'template': str(template_path),
            'errors': [f'{spec.template_relpath} 不存在，无法生成 {spec.config_relpath}。'],
        }

    template_data = _load_json(template_path, label=str(spec.template_relpath))
    template_schema = _schema_version(template_data, label=str(spec.template_relpath))
    template_harness = str(template_data.get('harness', '') or '').strip() if spec.key == 'overall' else ''

    if not config_path.exists():
        if dry_run:
            return {
                'success': False,
                'status': 'would_create',
                'config': str(config_path),
                'template': str(template_path),
                'schema_version': template_schema,
                'errors': [
                    f'{spec.config_relpath} 不存在；dry-run 不会从 {spec.template_relpath} 创建配置文件。'
                ],
            }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template_path, config_path)
        return {
            'success': True,
            'status': 'created',
            'config': str(config_path),
            'template': str(template_path),
            'schema_version': template_schema,
            **({'harness': template_harness} if template_harness else {}),
            'warnings': [f'已从 {spec.template_relpath} 创建 {spec.config_relpath}。'],
        }

    config_data = _load_json(config_path, label=str(spec.config_relpath))
    config_schema = _schema_version(config_data, label=str(spec.config_relpath))
    config_harness = str(config_data.get('harness', '') or '').strip() if spec.key == 'overall' else ''
    if config_schema != template_schema:
        return {
            'success': False,
            'status': 'schema_mismatch',
            'config': str(config_path),
            'template': str(template_path),
            'schema_version': config_schema,
            'expected_schema_version': template_schema,
            'errors': [
                (
                    f'{spec.config_relpath}.schema_version={config_schema}，'
                    f'但当前 {spec.template_relpath}.schema_version={template_schema}。'
                ),
                '请先迁移本地配置，再重新执行安装。',
            ],
        }

    return {
        'success': True,
        'status': 'present',
        'config': str(config_path),
        'template': str(template_path),
        'schema_version': config_schema,
        **({'harness': config_harness} if config_harness else {}),
    }


def ensure_install_configs(*, repo_root: str | Path, dry_run: bool = False) -> dict[str, Any]:
    repo_root_path = Path(repo_root)
    configs: dict[str, Any] = {}
    warnings: list[str] = []
    errors: list[str] = []

    for spec in CONFIG_SPECS:
        try:
            result = ensure_config_file(repo_root_path, spec, dry_run=dry_run)
        except (OSError, ValueError, KeyError) as exc:
            result = {
                'success': False,
                'status': 'failed',
                'errors': [str(exc)],
            }

        configs[spec.key] = result
        if isinstance(result.get('warnings'), list):
            warnings.extend(str(item) for item in result['warnings'] if str(item).strip())
        if not bool(result.get('success', False)):
            result_errors = result.get('errors')
            if isinstance(result_errors, list):
                errors.extend(str(item) for item in result_errors if str(item).strip())
            else:
                errors.append(f'{spec.label} 配置检查失败。')

    success = not errors
    created_count = sum(1 for item in configs.values() if item.get('status') == 'created')
    return {
        'success': success,
        'status': 'ok' if success else 'failed',
        'dry_run': dry_run,
        'created_count': created_count,
        'configs': configs,
        'warnings': warnings,
        'errors': errors,
    }
