#!/usr/bin/env python3
"""OpenClaw sessions-watch initialization entry.

这个入口只做编排：
- 先做重复任务预检
- 生成 session watch / known sessions 的初始化 plan
- 写入 known-direct-sessions.json 与 watch plist
- 安装/校验每日 system crontab 兜底任务（仅 --all / --generate-daily-init-cron）
- 自动 load 新生成的 plist
- `--all` 场景下，在所有 agent load 完成后，串行补跑一次 runtime

支持三种模式：
- --agent <id>：初始化单个 agent
- --all：初始化 OverallConfig.json 里的全部 agentId_list
- --generate-daily-init-cron：仅安装/校验 daily init cron，不碰 plist/registry

它和 `Sessions_Watch/Mechanisms/sessions_watch_runtime.py` 是并列入口，不互相调用。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Adapters.openclaw.openclaw_shared_funcs import LoadConfig, dbg, output_failure
from Adapters.openclaw.Sessions_Watch.Mechanisms.sessions_watch_funcs import (
    build_initialize_plan,
    build_openclaw_paths,
    build_session_watch_label,
    load_known_sessions,
    save_known_sessions,
)


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[4]


def _cfg(repo_root: str | Path | None = None) -> LoadConfig:
    return LoadConfig(Path(repo_root) if repo_root is not None else _repo_root_from_here())


def _uid() -> int:
    return os.getuid()


def _launchctl_print(target: str) -> dict:
    cmd = ["launchctl", "print", target]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "cmd": cmd,
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }


def _launchctl_load(plist_path: str) -> dict:
    cmd = ["launchctl", "load", "-w", plist_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "cmd": cmd,
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }


def _runtime_script_path(repo_root: Path) -> Path:
    adapter_dirname = str(_cfg(repo_root).openclaw_config.get('adapter_dirname', Path(__file__).resolve().parents[2].name) or Path(__file__).resolve().parents[2].name)
    return repo_root / "Adapters" / adapter_dirname / "Sessions_Watch" / "Mechanisms" / "sessions_watch_runtime.py"


def _run_runtime_for_agent(agent_id: str, *, repo_root: Path, dry_run: bool = False) -> dict:
    cmd = [sys.executable, str(_runtime_script_path(repo_root)), "--agent", agent_id, "--repo-root", str(repo_root)]
    if dry_run:
        return {"cmd": cmd, "dry_run": True, "returncode": 0, "stdout": "", "stderr": ""}
    proc = subprocess.run(cmd, capture_output=True, text=True)
    result = {
        "cmd": cmd,
        "dry_run": False,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }
    if proc.returncode == 0 and proc.stdout:
        try:
            result["parsed"] = json.loads(proc.stdout)
        except Exception:
            result["parsed"] = None
    return result


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


def _daily_write_time(repo_root: Path) -> str:
    overall_cfg = _cfg(repo_root).overall_config
    value = str(overall_cfg.get("daily_write_cron_time", "") or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        output_failure("OverallConfig.json.daily_write_cron_time 格式错误；应为 HH:MM")
    hour, minute = map(int, value.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        output_failure("OverallConfig.json.daily_write_cron_time 超出合法范围；应为 00:00-23:59")
    return value


def _session_watch_cron_hm(repo_root: Path, *, offset_minutes: int = 30) -> tuple[int, int]:
    daily_write_time = _daily_write_time(repo_root)
    hour, minute = map(int, daily_write_time.split(":"))
    total = (hour * 60 + minute + offset_minutes) % (24 * 60)
    return total // 60, total % 60


def _session_watch_cron_block(repo_root: Path) -> str:
    runtime_script = _runtime_script_path(repo_root)
    py = shlex.quote(sys.executable)
    script = shlex.quote(str(runtime_script))
    hour, minute = _session_watch_cron_hm(repo_root)
    hhmm = f"{hour:02d}:{minute:02d}"
    marker = str(_cfg(repo_root).openclaw_config['maintenance']['daily_init_cron_marker'])
    spacing = "#"
    header = f"# ===== MemoquasarEterna OpenClaw Sessions Watch Daily Init（每日 {hhmm}）====="
    begin = f"# BEGIN {marker}"
    cron_line = f"{minute} {hour} * * * {py} {script} --all"
    end = f"# END {marker}"
    return f"{spacing}\n{header}\n{begin}\n{cron_line}\n{end}"


def _ensure_daily_cron(repo_root: Path, *, dry_run: bool = False) -> dict:
    desired_block = _session_watch_cron_block(repo_root)
    desired_lines = desired_block.splitlines()
    current = _crontab_list()
    current_lines = [ln.rstrip() for ln in current.splitlines() if ln.strip()]
    marker = str(_cfg(repo_root).openclaw_config['maintenance']['daily_init_cron_marker'])
    begin_marker = f"# BEGIN {marker}"
    end_marker = f"# END {marker}"

    exact_exists = desired_block in current
    command_re = re.compile(r"(^|\s).*/Sessions_Watch/Mechanisms/sessions_watch_runtime\.py\s+--all(\s|$)")
    any_session_watch_begin_re = re.compile(r"^# BEGIN ai\.memory\.memoquasareterna\.openclaw\.session-watch\.daily-init\.")
    any_session_watch_end_re = re.compile(r"^# END ai\.memory\.memoquasareterna\.openclaw\.session-watch\.daily-init\.")

    has_current_block = False
    unmanaged_same_command: list[str] = []
    inside_any_session_watch_block = False
    for ln in current_lines:
        if ln == begin_marker:
            has_current_block = True
        if any_session_watch_begin_re.search(ln):
            inside_any_session_watch_block = True
        if command_re.search(ln) and not inside_any_session_watch_block:
            unmanaged_same_command.append(ln)
        if any_session_watch_end_re.search(ln):
            inside_any_session_watch_block = False

    if exact_exists:
        return {
            "changed": False,
            "dry_run": dry_run,
            "cron_block": desired_block,
            "status": "exists",
        }

    if unmanaged_same_command:
        output_failure(
            "检测到已有相同的 session-watch daily init cron 任务（未带管理标记），为避免重复安装已中止。\n"
            "请使用 crontab -l 检查并手动移除旧任务后再重新 install。"
        )

    new_lines = current_lines.copy()
    if has_current_block:
        filtered: list[str] = []
        inside_block = False
        for ln in new_lines:
            if ln == begin_marker:
                inside_block = True
                continue
            if ln == end_marker:
                inside_block = False
                continue
            if inside_block:
                continue
            filtered.append(ln)
        new_lines = filtered
    new_lines.extend(desired_lines)
    new_content = "\n".join(new_lines).strip() + "\n"

    if dry_run:
        return {
            "changed": True,
            "dry_run": True,
            "cron_block": desired_block,
            "status": "would-update" if has_current_block else "would-create",
        }

    result = _crontab_write(new_content)
    if result["returncode"] != 0:
        output_failure(f"写入 crontab 失败: {result['stderr'] or result['stdout']}")
    return {
        "changed": True,
        "dry_run": False,
        "cron_block": desired_block,
        "status": "updated" if has_current_block else "created",
        "crontab_write": result,
    }


def _file_content(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def _same_plist_content_exists(plist_content: str, launch_agents_dir: str) -> str | None:
    if not os.path.isdir(launch_agents_dir):
        return None
    for fname in os.listdir(launch_agents_dir):
        if not fname.endswith(".plist"):
            continue
        path = os.path.join(launch_agents_dir, fname)
        if _file_content(path) == plist_content:
            return path
    return None


def _same_job_loaded(paths: dict, agent_id: str) -> bool:
    result = _launchctl_print(f"gui/{_uid()}")
    if result["returncode"] != 0:
        return False
    text = result["stdout"]
    required = [
        paths["watch_script_path"],
        paths["sessions_index"],
        "--agent",
        agent_id,
    ]
    return all(token in text for token in required)


def _label_loaded(label: str) -> bool:
    result = _launchctl_print(f"gui/{_uid()}/{label}")
    return result["returncode"] == 0


def _label_path_exists(label: str, launch_agents_dir: str) -> bool:
    return os.path.exists(os.path.join(launch_agents_dir, f"{label}.plist"))


def _resolve_label_and_plan(agent_id: str, *, repo_root: str | Path | None = None, suffix_start: str | int | None = None) -> tuple[str, dict]:
    cfg = _cfg(repo_root)
    launch_agents_dir = os.path.expanduser(cfg.openclaw_config["maintenance"]["launch_agents_dir"])
    suffix = suffix_start
    while True:
        label = build_session_watch_label(agent_id, suffix=suffix, repo_root=repo_root)
        paths = build_openclaw_paths(agent_id, repo_root=repo_root, label=label)
        plan = build_initialize_plan(agent_id, repo_root=repo_root, label=label, suffix=suffix)
        duplicate_path = _same_plist_content_exists(plan["plist_content"], launch_agents_dir)
        if duplicate_path:
            output_failure(
                "已有完全相同的 watch 任务，已在运行或已落盘。\n"
                "请使用 list 查看，update 更新；如需重新初始化，请先使用 delete 删除现有任务。\n"
                f"duplicate_plist={duplicate_path}"
            )
        if _same_job_loaded(paths, agent_id):
            output_failure(
                "已有完全相同的 watch 任务正在运行。\n"
                "请使用 list 查看，update 更新；如需重新初始化，请先使用 delete 删除现有任务。"
            )
        if _label_path_exists(label, launch_agents_dir) or _label_loaded(label):
            if suffix is None:
                dbg(f"label 已存在，改为从 suffix=1 开始尝试: {label}")
                suffix = 1
                continue
            if isinstance(suffix, int) or (isinstance(suffix, str) and suffix.isdigit()):
                dbg(f"label 已存在，尝试下一个 suffix: {label}")
                suffix = int(suffix) + 1
                continue
            output_failure(
                "指定的 label 已存在，且 suffix 为非数字字符串，无法自动递增。\n"
                "请更换 --label-suffix，或先使用 delete 删除现有任务。"
            )
        return label, plan


def _install_one_agent(agent_id: str, *, repo_root: Path, label_suffix: str | int) -> dict:
    label, plan = _resolve_label_and_plan(agent_id, repo_root=repo_root, suffix_start=label_suffix)
    paths = plan["paths"]
    save_known_sessions(paths["known_sessions_path"], plan["known_sessions_seed"])
    with open(paths["plist_path"], "w", encoding="utf-8") as f:
        f.write(plan["plist_content"])
    load_result = _launchctl_load(paths["plist_path"])
    if load_result["returncode"] != 0:
        output_failure(f"install load 失败: {load_result['stderr'] or load_result['stdout']}")
    return {
        "success": True,
        "agent_id": agent_id,
        "label": label,
        "known_sessions_path": paths["known_sessions_path"],
        "plist_path": paths["plist_path"],
        "launchd_load": load_result,
    }


def _install_all_agents(*, repo_root: Path, label_suffix: str | int) -> dict:
    cfg = _cfg(repo_root)
    agent_ids = cfg.overall_config["agentId_list"]
    install_results = []
    runtime_results = []
    for agent_id in agent_ids:
        install_results.append(_install_one_agent(agent_id, repo_root=repo_root, label_suffix=label_suffix))
    for agent_id in agent_ids:
        runtime_result = _run_runtime_for_agent(agent_id, repo_root=repo_root, dry_run=False)
        if runtime_result["returncode"] != 0:
            output_failure(
                f"初始化后串行触发 runtime 失败: agent={agent_id}; "
                f"stderr={runtime_result['stderr'] or runtime_result['stdout']}"
            )
        runtime_results.append(runtime_result)
    return {
        "success": True,
        "mode": "all",
        "agents": install_results,
        "runtime_runs": runtime_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClaw sessions-watch initialization entry")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--agent", help="agent id")
    group.add_argument("--all", action="store_true", help="初始化 OverallConfig.json 里的全部 agentId_list")
    group.add_argument("--generate-daily-init-cron", action="store_true", help="仅生成/校验 daily init cron，不碰 plist/registry")
    parser.add_argument("--dry-run", action="store_true", help="只输出计划，不写文件")
    parser.add_argument("--write", action="store_true", help="写入初始化产物")
    parser.add_argument("--label-suffix", default=None, help="label 后缀起点；默认先不带 suffix，只有冲突时才自动从 1 开始递增，也可手动传 test 之类的字符串")
    parser.add_argument("--repo-root", default=None, help="仓库根目录（默认自动推断）")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else _repo_root_from_here()

    if args.generate_daily_init_cron:
        cron_result = _ensure_daily_cron(repo_root, dry_run=not args.write)
        result = {
            "success": True,
            "dry_run": not args.write,
            "mode": "cron-only",
            "cron_install": cron_result,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.all:
        cron_result = _ensure_daily_cron(repo_root, dry_run=not args.write)
        if not args.write:
            result = {
                "success": True,
                "dry_run": True,
                "mode": "all",
                "cron_install": cron_result,
                "note": "dry-run 模式下只预检，不写 plist / known-direct-sessions.json",
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        result = _install_all_agents(repo_root=repo_root, label_suffix=args.label_suffix)
        result["cron_install"] = cron_result
        result["dry_run"] = False
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    label, plan = _resolve_label_and_plan(args.agent, repo_root=repo_root, suffix_start=args.label_suffix)

    if args.write:
        paths = plan["paths"]
        save_known_sessions(paths["known_sessions_path"], plan["known_sessions_seed"])
        with open(paths["plist_path"], "w", encoding="utf-8") as f:
            f.write(plan["plist_content"])
        load_result = _launchctl_load(paths["plist_path"])
        if load_result["returncode"] != 0:
            output_failure(f"install load 失败: {load_result['stderr'] or load_result['stdout']}")
        runtime_result = _run_runtime_for_agent(args.agent, repo_root=repo_root, dry_run=False)
        if runtime_result["returncode"] != 0:
            output_failure(
                f"单 agent 初始化后触发 runtime 失败: agent={args.agent}; "
                f"stderr={runtime_result['stderr'] or runtime_result['stdout']}"
            )
        result = {
            "success": True,
            "dry_run": False,
            "mode": "single",
            "label": label,
            "plan": plan,
            "known_sessions_path": paths["known_sessions_path"],
            "launchd_load": load_result,
            "runtime_run": runtime_result,
        }
    else:
        result = {
            "success": True,
            "dry_run": True,
            "mode": "single",
            "label": label,
            "plan": plan,
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
