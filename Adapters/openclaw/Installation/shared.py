from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from Adapters.openclaw.openclaw_shared_funcs import LoadConfig
from Core.shared_funcs import get_memory_worker_harness, get_production_agents


DEFAULT_OPENCLAW_ROOT = '~/.openclaw'
OPENCLAW_CONFIG_PATH = Path(__file__).resolve().parents[1] / 'OpenclawConfig.json'


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[3]


def cfg(repo_root: str | Path | None = None) -> LoadConfig:
    return LoadConfig(Path(repo_root) if repo_root is not None else repo_root_from_here())


def require_openclaw_memory_worker_harness(config: LoadConfig, *, action: str) -> dict[str, Any] | None:
    if get_memory_worker_harness(config.overall_config) == 'openclaw':
        return None
    return {
        'success': False,
        'status': 'failed',
        'failed_step': 'preflight',
        'message': f'OverallConfig.json.memory_worker_harness 不是 openclaw，无法执行 OpenClaw {action}。',
    }


def require_openclaw_harness(config: LoadConfig, *, action: str) -> dict[str, Any] | None:
    return require_openclaw_memory_worker_harness(config, action=action)


def load_openclaw_config_dict() -> dict[str, Any]:
    with open(OPENCLAW_CONFIG_PATH, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f'OpenclawConfig.json 格式错误: {OPENCLAW_CONFIG_PATH}')
    return data


def write_openclaw_config_dict(data: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    with open(OPENCLAW_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt_nonempty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print('输入不能为空，请重新输入。', file=sys.stderr)


def replace_openclaw_root_prefix(node: Any, *, old_prefix: str, new_prefix: str) -> Any:
    if isinstance(node, str):
        if node == old_prefix:
            return new_prefix
        if node.startswith(old_prefix + '/'):
            return new_prefix + node[len(old_prefix):]
        return node
    if isinstance(node, list):
        return [replace_openclaw_root_prefix(item, old_prefix=old_prefix, new_prefix=new_prefix) for item in node]
    if isinstance(node, dict):
        return {key: replace_openclaw_root_prefix(value, old_prefix=old_prefix, new_prefix=new_prefix) for key, value in node.items()}
    return node


def check_and_maybe_patch_openclaw_root(config_data: dict[str, Any], *, dry_run: bool) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    warnings: list[str] = []
    default_root = Path(DEFAULT_OPENCLAW_ROOT).expanduser()
    if default_root.exists():
        return config_data, {
            'status': 'ok',
            'root': str(default_root),
            'config_updated': False,
            'prompted': False,
        }, warnings

    if not is_interactive():
        raise RuntimeError(
            f'找不到默认 OpenClaw 根目录 {default_root}，且当前不是交互式终端；无法询问实际安装位置。'
        )

    print(
        f'找不到默认 OpenClaw 根目录：{default_root}\n'
        '请确认你 OpenClaw 的实际安装根目录，并输入该目录路径。',
        file=sys.stderr,
    )
    while True:
        raw_input_root = prompt_nonempty('OpenClaw root path: ')
        candidate = Path(raw_input_root).expanduser()
        if candidate.exists() and candidate.is_dir():
            break
        print('输入路径不存在或不是目录，请重新输入。', file=sys.stderr)

    patched = replace_openclaw_root_prefix(config_data, old_prefix=DEFAULT_OPENCLAW_ROOT, new_prefix=raw_input_root)
    warnings.append(f'已将 OpenclawConfig.json 中以 {DEFAULT_OPENCLAW_ROOT} 为前缀的路径模板改写为 {raw_input_root}。')
    return patched, {
        'status': 'updated' if not dry_run else 'would-update',
        'root': str(candidate),
        'config_updated': True,
        'prompted': True,
    }, warnings


def production_agent_ids(config: LoadConfig, agent_ids: list[str] | None = None) -> list[str]:
    configured = get_production_agents(config.overall_config)
    openclaw_agents = [item['agentId'] for item in configured if item['harness'] == 'openclaw']
    if agent_ids is None:
        parsed = openclaw_agents
    else:
        requested = [str(item).strip() for item in agent_ids if str(item).strip()]
        openclaw_set = set(openclaw_agents)
        invalid = [item for item in requested if item not in openclaw_set]
        if invalid:
            raise RuntimeError(f'以下 production agent 不属于 openclaw harness: {", ".join(invalid)}')
        parsed = requested
    if not parsed:
        raise RuntimeError('OverallConfig.json.production_agents 中没有 openclaw production agent，无法验证 production agent 配置')
    return parsed


def plugin_id_from_product_name(product_name: str) -> str:
    plugin_id = ''.join(ch.lower() if ch.isalnum() else '_' for ch in product_name).strip('_')
    return plugin_id or 'memoquasar_read'


def plugin_install_root() -> Path:
    base = os.environ.get('OPENCLAW_EXTENSIONS_PATH', '').strip()
    if base:
        return Path(base).expanduser()
    return Path('~/.openclaw/extensions').expanduser()


def memory_worker_workspace_path(config: LoadConfig) -> Path:
    worker_agent_id = str(config.overall_config.get('memory_worker_agentId', '') or '').strip()
    if not worker_agent_id:
        raise KeyError('OverallConfig.json 缺少 memory_worker_agentId')
    template = str(config.openclaw_config.get('memory_worker_agent_workspace_path', '') or '').strip()
    if not template:
        raise KeyError('OpenclawConfig.json 缺少 memory_worker_agent_workspace_path')
    return Path(template.format(memory_worker_agentId=worker_agent_id)).expanduser()


def render_sessions_path(config_data: dict[str, Any], *, repo_root: Path, agent_id: str) -> Path:
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


def sessions_json_path(config_data: dict[str, Any], *, repo_root: Path, agent_id: str) -> Path:
    return render_sessions_path(config_data, repo_root=repo_root, agent_id=agent_id) / 'sessions.json'


def render_registry_key(config_data: dict[str, Any], *, agent_id: str) -> str:
    rules = config_data.get('sessions_registry_maintenance')
    if not isinstance(rules, dict):
        raise RuntimeError('OpenclawConfig.json 缺少 sessions_registry_maintenance')
    key_template = str(rules.get('key_template', '') or '').strip()
    if not key_template:
        raise RuntimeError('OpenclawConfig.json.sessions_registry_maintenance 缺少 key_template')
    if '{agentId}' not in key_template:
        raise RuntimeError('OpenclawConfig.json.sessions_registry_maintenance.key_template 必须包含 {agentId}')
    return key_template.format(agentId=agent_id)


def load_sessions_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f'sessions.json 不存在: {path}')
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f'sessions.json 格式错误: {path}')
    return data


def verify_registry_maintenance_for_agent(config_data: dict[str, Any], *, repo_root: Path, agent_id: str) -> tuple[bool, dict[str, Any]]:
    sessions_json = sessions_json_path(config_data, repo_root=repo_root, agent_id=agent_id)
    sessions_data = load_sessions_json(sessions_json)
    rendered_key = render_registry_key(config_data, agent_id=agent_id)
    exists = rendered_key in sessions_data
    return exists, {
        'agent_id_test': agent_id,
        'sessions_json_test': str(sessions_json),
        'rendered_key_test': rendered_key,
    }


def prompt_registry_maintenance_fields(current_rules: dict[str, Any]) -> dict[str, Any]:
    updated = dict(current_rules)
    default = str(updated.get('key_template', '') or '').strip()
    if default:
        value = input(f"sessions_registry_maintenance.key_template [{default}] ").strip()
        updated['key_template'] = value or default
    else:
        updated['key_template'] = prompt_nonempty('sessions_registry_maintenance.key_template: ')
    return updated


def emit_registry_help(metadata: dict[str, Any], *, preface: str | None = None) -> None:
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


def check_and_maybe_fill_registry_maintenance(config_data: dict[str, Any], *, repo_root: Path, agent_ids: list[str], dry_run: bool) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    warnings: list[str] = []
    rules = config_data.get('sessions_registry_maintenance')
    if not isinstance(rules, dict):
        raise RuntimeError('OpenclawConfig.json 缺少 sessions_registry_maintenance')

    failed_metadata: list[dict[str, Any]] = []
    passed_metadata: list[dict[str, Any]] = []
    for agent_id in agent_ids:
        ok, metadata = verify_registry_maintenance_for_agent(config_data, repo_root=repo_root, agent_id=agent_id)
        if ok:
            passed_metadata.append(metadata)
        else:
            failed_metadata.append(metadata)
    if not failed_metadata:
        return config_data, {
            'status': 'ok',
            'config_updated': False,
            'prompted_fields': [],
            'agent_count': len(agent_ids),
            'agents': passed_metadata,
        }, warnings

    if not is_interactive():
        first = failed_metadata[0]
        raise RuntimeError(
            'OpenclawConfig.json.sessions_registry_maintenance.key_template 当前无法通过真实 sessions.json 校验，'
            f"测试文件: {first['sessions_json_test']}，"
            f"渲染 key: {first['rendered_key_test']}；且当前不是交互式终端，无法补全。"
        )

    emit_registry_help(
        failed_metadata[0],
        preface='OpenclawConfig.json.sessions_registry_maintenance.key_template 当前无法通过真实 sessions.json 校验。\n请重新输入 key_template。',
    )

    updated_config = dict(config_data)
    prompted_fields = ['key_template']
    attempts = 3
    last_failed = failed_metadata[0]
    last_error_message: str | None = None
    for idx in range(1, attempts + 1):
        updated_rules = prompt_registry_maintenance_fields(dict(updated_config.get('sessions_registry_maintenance', {})))
        updated_config['sessions_registry_maintenance'] = updated_rules
        current_failed: list[dict[str, Any]] = []
        current_passed: list[dict[str, Any]] = []
        last_error_message = None
        for agent_id in agent_ids:
            try:
                ok, verify_metadata = verify_registry_maintenance_for_agent(updated_config, repo_root=repo_root, agent_id=agent_id)
            except Exception as exc:
                ok = False
                last_error_message = str(exc)
                try:
                    rendered_key = render_registry_key(updated_config, agent_id=agent_id)
                except Exception:
                    rendered_key = last_failed['rendered_key_test']
                verify_metadata = {
                    'agent_id_test': agent_id,
                    'sessions_json_test': str(sessions_json_path(updated_config, repo_root=repo_root, agent_id=agent_id)),
                    'rendered_key_test': rendered_key,
                }
            if ok:
                current_passed.append(verify_metadata)
            else:
                current_failed.append(verify_metadata)
        if not current_failed:
            warnings.append('已交互修正 OpenclawConfig.json.sessions_registry_maintenance，并通过所有 production agent 的真实 sessions.json 校验。')
            return updated_config, {
                'status': 'updated' if not dry_run else 'would-update',
                'config_updated': True,
                'prompted_fields': prompted_fields,
                'attempts': idx,
                'agent_count': len(agent_ids),
                'agents': current_passed,
            }, warnings
        last_failed = current_failed[0]
        if idx < attempts:
            if last_error_message:
                print(f'验证失败：{last_error_message}。请重试。', file=sys.stderr)
            else:
                print('验证失败：当前 key_template 仍无法命中至少一个 sessions.json 中的目标 key，请重试。', file=sys.stderr)

    raise RuntimeError(
        'sessions_registry_maintenance.key_template 连续 3 次交互后仍无法通过所有 production agent 的真实 sessions.json 校验。\n'
        + (f'最后一次错误：{last_error_message}\n' if last_error_message else '')
        + f"请检查文件：{last_failed['sessions_json_test']}\n"
        + f"最后一次渲染 key：{last_failed['rendered_key_test']}"
    )


def shell_step(script_path: Path, *, repo_root: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    cmd = ['bash', str(script_path)]
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_root), env=proc_env)
    return {
        'cmd': cmd,
        'returncode': proc.returncode,
        'stdout': (proc.stdout or '').strip(),
        'stderr': (proc.stderr or '').strip(),
        'parsed': None,
    }


def python_step(script_path: Path, *, args: list[str], repo_root: Path | None, dry_run: bool) -> dict[str, Any]:
    cmd = [sys.executable, str(script_path)]
    if repo_root is not None:
        cmd.extend(['--repo-root', str(repo_root)])
    cmd.extend(args)
    if dry_run:
        cmd.append('--dry-run')
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stdout = (proc.stdout or '').strip()
    stderr = (proc.stderr or '').strip()
    parsed = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except Exception:
            parsed = None
    return {
        'cmd': cmd,
        'returncode': proc.returncode,
        'stdout': stdout,
        'stderr': stderr,
        'parsed': parsed,
    }


def summarize_step_result(result: dict[str, Any]) -> dict[str, Any]:
    parsed = result.get('parsed') if isinstance(result, dict) else None
    summary: dict[str, Any] = {}
    if isinstance(parsed, dict):
        for key in (
            'mode',
            'output_path',
            'target_root',
            'worker_agent_id',
            'memory_worker_agentId',
            'memory_worker_workspace_path',
            'read_plugin_id',
            'agent_count',
            'status',
            'cron_install',
            'labels',
            'cron_cleanup',
        ):
            if key in parsed:
                summary[key] = parsed[key]
    if result.get('returncode', 0) != 0:
        if result.get('stderr'):
            summary['error'] = result['stderr']
        elif result.get('stdout'):
            summary['error'] = result['stdout']
    return summary


def critical_failure_payload(*, step_results: list[dict[str, Any]], failed_step: str, message: str) -> dict[str, Any]:
    return {
        'success': False,
        'status': 'failed',
        'failed_step': failed_step,
        'message': message,
        'steps': step_results,
    }


def remove_tree(path: Path, *, dry_run: bool) -> dict[str, Any]:
    exists = path.exists()
    if dry_run:
        return {
            'path': str(path),
            'exists': exists,
            'deleted': False,
            'status': 'would-delete' if exists else 'skipped',
        }
    if not exists:
        return {
            'path': str(path),
            'exists': False,
            'deleted': False,
            'status': 'skipped',
        }
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return {
        'path': str(path),
        'exists': True,
        'deleted': True,
        'status': 'deleted',
    }
