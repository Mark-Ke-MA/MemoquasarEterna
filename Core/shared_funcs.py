"""清洁版记忆系统共享函数。

这里只保留 MemoquasarEterna 全局复用的最小公共面：
- 调试与 JSON 输出
- 配置加载与校验
- 原子 JSON 读写
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# 日志 / JSON 读写
# ---------------------------------------------------------------------------


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


def load_json_file(path: str | Path) -> Any:
    """读取 JSON 文件。"""
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_json_atomic(path: str | Path, data: Any, *, indent: int = 2):
    """原子写入 JSON。"""
    path = str(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CleanMemoryPaths:
    """clean 版路径信息。"""

    repo_root: Path
    code_root: str
    store_root: str
    overall_config: dict[str, Any]


class LoadConfig:
    """加载 clean 版总配置。"""

    def __init__(self, repo_root: str | Path | None = None):
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
        self.overall_config = self.load_overall_config()
        self.code_root = os.path.expanduser(self.overall_config['code_dir'])
        self.store_root = os.path.expanduser(self.overall_config['store_dir'])

    def load_overall_config(self) -> dict:
        path = self.repo_root / 'OverallConfig.json'
        if not path.exists():
            raise FileNotFoundError(f'OverallConfig.json 不存在: {path}')
        data = load_json_file(path)
        if not isinstance(data, dict):
            raise ValueError(f'OverallConfig.json 格式错误: {path}')
        for key in ('agentId_list', 'code_dir', 'store_dir', 'store_dir_structure', 'window', 'layer1_write', 'active_schema_version', 'archive_schema_version'):
            if key not in data:
                raise KeyError(f'OverallConfig.json 缺少 {key}')
        return data


def require_keys(data: dict, keys: Iterable[str], *, where: str = 'config'):
    """检查字典是否包含必需键。"""
    missing = [key for key in keys if key not in data]
    if missing:
        raise KeyError(f'{where} 缺少键: {", ".join(missing)}')


__all__ = [
    'dbg',
    'output_success',
    'output_failure',
    'load_json_file',
    'write_json_atomic',
    'CleanMemoryPaths',
    'LoadConfig',
    'require_keys',
]
