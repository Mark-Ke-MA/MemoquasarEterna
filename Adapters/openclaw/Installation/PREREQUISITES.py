#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Adapters.openclaw.openclaw_shared_funcs import LoadConfig, output_success


DEFAULT_OPENCLAW_ROOT = '~/.openclaw'
OPENCLAW_CONFIG_PATH = Path(__file__).resolve().parents[1] / 'OpenclawConfig.json'


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[3]


def _cfg(repo_root: str | Path | None = None) -> LoadConfig:
    return LoadConfig(Path(repo_root) if repo_root is not None else _repo_root_from_here())


def _load_openclaw_config_dict() -> dict[str, Any]:
    with open(OPENCLAW_CONFIG_PATH, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f'OpenclawConfig.json 格式错误: {OPENCLAW_CONFIG_PATH}')
    return data


def _write_openclaw_config_dict(data: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    with open(OPENCLAW_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_nonempty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print('输入不能为空，请重新输入。', file=sys.stderr)


def _replace_openclaw_root_prefix(node: Any, *, old_prefix: str, new_prefix: str) -> Any:
    if isinstance(node, str):
        if node == old_prefix:
            return new_prefix
        if node.startswith(old_prefix + '/'):
            return new_prefix + node[len(old_prefix):]
        return node
    if isinstance(node, list):
        return [_replace_openclaw_root_prefix(item, old_prefix=old_prefix, new_prefix=new_prefix) for item in node]
    if isinstance(node, dict):
        return {key: _replace_openclaw_root_prefix(value, old_prefix=old_prefix, new_prefix=new_prefix) for key, value in node.items()}
    return node


def _render_sessions_path(config_data: dict[str, Any], *, repo_root: Path, agent_id: str) -> Path:
    adapter_dirname = str(config_data.get('adapter_dirname', 'openclaw') or 'openclaw')
    template = str(config_data.get('sessions_path', '') or '').strip()
    if not template:
        raise RuntimeError('OpenclawConfig.json 缺少 sessions_path')
    rendered = template.format(
        agentId=agent_id,
        agent_id=agent_id,
        code_dir=str(repo_root),
        adapter_dirname=adapter_dirname,
    )
    return Path(os.path.expanduser(rendered))


def _sessions_json_path(config_data: dict[str, Any], *, repo_root: Path, agent_id: str) -> Path:
    return _render_sessions_path(config_data, repo_root=repo_root, agent_id=agent_id) / 'sessions.json'


def _render_registry_key(config_data: dict[str, Any], *, agent_id: str) -> str:
    rules = config_data.get('sessions_registry_maintenance')
    if not isinstance(rules, dict):
        raise RuntimeError('OpenclawConfig.json 缺少 sessions_registry_maintenance')
    key_template = str(rules.get('key_template', '') or '').strip()
    if not key_template:
        raise RuntimeError('OpenclawConfig.json.sessions_registry_maintenance 缺少 key_template')
    if '{agentId}' not in key_template:
        raise RuntimeError('OpenclawConfig.json.sessions_registry_maintenance.key_template 必须包含 {agentId}')
    return key_template.format(agentId=agent_id)


def _load_sessions_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f'sessions.json 不存在: {path}')
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f'sessions.json 格式错误: {path}')
    return data


def _check_and_maybe_patch_openclaw_root(config_data: dict[str, Any], *, dry_run: bool) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    warnings: list[str] = []
    default_root = Path(DEFAULT_OPENCLAW_ROOT).expanduser()
    if default_root.exists():
        return config_data, {
            'status': 'ok',
            'root': str(default_root),
            'config_updated': False,
            'prompted': False,
        }, warnings

    if not _is_interactive():
        raise RuntimeError(
            f'找不到默认 OpenClaw 根目录 {default_root}，且当前不是交互式终端；无法询问实际安装位置。'
        )

    print(
        f'找不到默认 OpenClaw 根目录：{default_root}\n'
        '请确认你 OpenClaw 的实际安装根目录，并输入该目录路径。',
        file=sys.stderr,
    )
    while True:
        raw_input_root = _prompt_nonempty('OpenClaw root path: ')
        candidate = Path(raw_input_root).expanduser()
        if candidate.exists() and candidate.is_dir():
            break
        print('输入路径不存在或不是目录，请重新输入。', file=sys.stderr)

    old_prefix = DEFAULT_OPENCLAW_ROOT
    new_prefix = raw_input_root
    patched = _replace_openclaw_root_prefix(config_data, old_prefix=old_prefix, new_prefix=new_prefix)
    warnings.append(f'已将 OpenclawConfig.json 中以 {old_prefix} 为前缀的路径模板改写为 {new_prefix}。')
    return patched, {
        'status': 'updated' if not dry_run else 'would-update',
        'root': str(candidate),
        'config_updated': True,
        'prompted': True,
    }, warnings


def _verify_registry_maintenance(config_data: dict[str, Any], *, repo_root: Path) -> tuple[bool, dict[str, Any]]:
    cfg = _cfg(repo_root)
    agent_ids = cfg.overall_config.get('agentId_list')
    if not isinstance(agent_ids, list) or not agent_ids:
        raise RuntimeError('OverallConfig.json.agentId_list 为空，无法验证 sessions_registry_maintenance')
    agent_id_test = str(agent_ids[0]).strip()
    if not agent_id_test:
        raise RuntimeError('OverallConfig.json.agentId_list[0] 为空，无法验证 sessions_registry_maintenance')

    sessions_json = _sessions_json_path(config_data, repo_root=repo_root, agent_id=agent_id_test)
    sessions_data = _load_sessions_json(sessions_json)
    rendered_key = _render_registry_key(config_data, agent_id=agent_id_test)
    exists = rendered_key in sessions_data
    return exists, {
        'agent_id_test': agent_id_test,
        'sessions_json_test': str(sessions_json),
        'rendered_key_test': rendered_key,
    }


def _prompt_registry_maintenance_fields(current_rules: dict[str, Any]) -> dict[str, Any]:
    updated = dict(current_rules)
    default = str(updated.get('key_template', '') or '').strip()
    if default:
        value = input(f"sessions_registry_maintenance.key_template [{default}] ").strip()
        updated['key_template'] = value or default
    else:
        updated['key_template'] = _prompt_nonempty('sessions_registry_maintenance.key_template: ')
    return updated


def _emit_registry_help(metadata: dict[str, Any], *, preface: str | None = None) -> None:
    prefix = '' if not preface else f'{preface}\n'
    print(
        prefix
        + f"本次验证使用的 agentId: {metadata['agent_id_test']}\n"
        + f"请检查以下文件：{metadata['sessions_json_test']}\n"
        + '如果你不知道具体的 key_template 格式，请在 sessions.json 中找到你希望记住的聊天记录所对应的顶层字段。\n'
        + '它可能类似于：\n'
        + 'agent:你的agent名:main\n'
        + 'agent:你的agent名:telegram:direct:1234567890\n'
        + '填写 key_template 时，请将其中的“你的agent名”替换为：{agentId}\n'
        + '例如可写成：\n'
        + 'agent:{agentId}:main\n'
        + 'agent:{agentId}:telegram:direct:1234567890\n'
        + f"当前根据你的输入渲染出的 key 是：{metadata['rendered_key_test']}\n"
        + '注意：key_template 中必须包含 {agentId}。',
        file=sys.stderr,
    )


def _check_and_maybe_fill_registry_maintenance(config_data: dict[str, Any], *, repo_root: Path, dry_run: bool) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    warnings: list[str] = []
    rules = config_data.get('sessions_registry_maintenance')
    if not isinstance(rules, dict):
        raise RuntimeError('OpenclawConfig.json 缺少 sessions_registry_maintenance')

    try:
        ok, metadata = _verify_registry_maintenance(config_data, repo_root=repo_root)
    except Exception as exc:
        raise RuntimeError(str(exc))
    if ok:
        return config_data, {
            'status': 'ok',
            'config_updated': False,
            'prompted_fields': [],
            **metadata,
        }, warnings

    if not _is_interactive():
        raise RuntimeError(
            'OpenclawConfig.json.sessions_registry_maintenance.key_template 当前无法通过真实 sessions.json 校验，'
            f"测试文件: {metadata['sessions_json_test']}，"
            f"渲染 key: {metadata['rendered_key_test']}；且当前不是交互式终端，无法补全。"
        )

    _emit_registry_help(
        metadata,
        preface='OpenclawConfig.json.sessions_registry_maintenance.key_template 当前无法通过真实 sessions.json 校验。\n请重新输入 key_template。',
    )

    updated_config = dict(config_data)
    prompted_fields = ['key_template']
    attempts = 3
    last_metadata = metadata
    last_error_message: str | None = None
    for idx in range(1, attempts + 1):
        updated_rules = _prompt_registry_maintenance_fields(dict(updated_config.get('sessions_registry_maintenance', {})))
        updated_config['sessions_registry_maintenance'] = updated_rules
        try:
            ok, verify_metadata = _verify_registry_maintenance(updated_config, repo_root=repo_root)
            last_metadata = verify_metadata
            last_error_message = None
        except Exception as exc:
            ok = False
            last_error_message = str(exc)
            try:
                rendered_key = _render_registry_key(updated_config, agent_id=metadata['agent_id_test'])
            except Exception:
                rendered_key = metadata['rendered_key_test']
            last_metadata = {
                'agent_id_test': metadata['agent_id_test'],
                'sessions_json_test': metadata['sessions_json_test'],
                'rendered_key_test': rendered_key,
            }
        if ok:
            warnings.append('已交互修正 OpenclawConfig.json.sessions_registry_maintenance，并通过真实 sessions.json 校验。')
            return updated_config, {
                'status': 'updated' if not dry_run else 'would-update',
                'config_updated': True,
                'prompted_fields': prompted_fields,
                'attempts': idx,
                **last_metadata,
            }, warnings
        if idx < attempts:
            if last_error_message:
                print(f'验证失败：{last_error_message}。请重试。', file=sys.stderr)
            else:
                print('验证失败：当前 key_template 仍无法命中 sessions.json 中的目标 key，请重试。', file=sys.stderr)

    raise RuntimeError(
        'sessions_registry_maintenance.key_template 连续 3 次交互后仍无法通过真实 sessions.json 校验。\n'
        + (f'最后一次错误：{last_error_message}\n' if last_error_message else '')
        + f"请检查文件：{last_metadata['sessions_json_test']}\n"
        + f"最后一次渲染 key：{last_metadata['rendered_key_test']}"
    )


def run_prerequisites(*, repo_root: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    repo_root_path = Path(repo_root) if repo_root is not None else _repo_root_from_here()
    cfg = _cfg(repo_root_path)

    if str(cfg.overall_config.get('harness', '') or '').strip() != 'openclaw':
        return {
            'success': False,
            'status': 'failed',
            'message': 'OverallConfig.json.harness 不是 openclaw，无法执行 OpenClaw prerequisites。',
        }

    config_data = _load_openclaw_config_dict()

    root_check: dict[str, Any]
    registry_check: dict[str, Any]
    warnings: list[str] = []

    try:
        config_data, root_check, root_warnings = _check_and_maybe_patch_openclaw_root(config_data, dry_run=dry_run)
        warnings.extend(root_warnings)
        config_data, registry_check, registry_warnings = _check_and_maybe_fill_registry_maintenance(
            config_data,
            repo_root=repo_root_path,
            dry_run=dry_run,
        )
        warnings.extend(registry_warnings)
    except Exception as exc:
        return {
            'success': False,
            'status': 'failed',
            'message': str(exc),
        }

    config_updated = bool(root_check.get('config_updated') or registry_check.get('config_updated'))
    if config_updated:
        _write_openclaw_config_dict(config_data, dry_run=dry_run)

    return {
        'success': True,
        'status': 'success_with_warnings' if warnings else 'success',
        'dry_run': dry_run,
        'config_updated': config_updated,
        'checks': {
            'openclaw_root': root_check,
            'sessions_registry_maintenance': registry_check,
        },
        'warnings': warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='OpenClaw prerequisites check and interactive config completion.')
    parser.add_argument('--repo-root', default=None, help='仓库根目录（默认自动推断）')
    parser.add_argument('--dry-run', action='store_true', help='只执行检查与交互预览，不实际写回 OpenclawConfig.json')
    args = parser.parse_args()
    output_success(run_prerequisites(repo_root=args.repo_root, dry_run=args.dry_run))


if __name__ == '__main__':
    main()
