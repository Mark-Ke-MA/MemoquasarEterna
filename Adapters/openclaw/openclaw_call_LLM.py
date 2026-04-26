#!/usr/bin/env python3
"""OpenClaw Layer1 Write runtime bridge.

最小职责：
- 输入一个 prompt
- 启动一个 memory worker subagent session
- 阻塞等待，直到 session 结束
- 返回 session 结束结果

不负责：
- 不读写结果文件
- 不做旧版兼容
- 不做产物校验
- 不做额外 fallback
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


REQUESTER_SESSION_KEY = os.environ.get("OPENCLAW_LAYER1_REQUESTER_SESSION_KEY", "").strip() or None
WAIT_TIMEOUT_MS = int(os.environ.get("OPENCLAW_LAYER1_WRITE_RUNTIME_TIMEOUT_MS", "1800000"))


def _with_silent_completion_contract(prompt: str) -> str:
    return (
        f"{prompt.rstrip()}\n\n"
        "[MemoquasarEterna OpenClaw adapter instruction]\n"
        "After completing every required file write or tool action, your final assistant response "
        "MUST be exactly:\n"
        "NO_REPLY\n"
        "Do not summarize, explain, report status, add punctuation, wrap it in markdown, or send "
        "any other completion message."
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_memory_worker_agent_id() -> str:
    overall_config_path = _repo_root() / 'OverallConfig.json'
    with open(overall_config_path, encoding='utf-8') as f:
        overall_cfg = json.load(f)
    if not isinstance(overall_cfg, dict):
        raise TypeError(f'OverallConfig.json 顶层必须是 object: {overall_config_path}')
    memory_worker_agent_id = str(overall_cfg.get('memory_worker_agentId', '') or '').strip()
    if not memory_worker_agent_id:
        raise KeyError(f'OverallConfig.json 缺少 memory_worker_agentId: {overall_config_path}')
    return memory_worker_agent_id


MEMORY_WORKER_AGENT_ID = _load_memory_worker_agent_id()


def _parse_strict_json_stdout(text: str) -> dict[str, Any] | None:
    if not text or not text.strip():
        return None
    try:
        parsed = json.loads(text.strip())
    except Exception:  # noqa: BLE001
        return None
    return parsed if isinstance(parsed, dict) else None


def _resolve_openclaw_dist_dir() -> Path:
    configured = os.environ.get("OPENCLAW_DIST_DIR", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            Path("/opt/homebrew/lib/node_modules/openclaw/dist"),
            Path("/usr/local/lib/node_modules/openclaw/dist"),
        ]
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "OpenClaw dist directory not found. Set OPENCLAW_DIST_DIR to the installed openclaw/dist path."
    )


def _select_single_chunk(
    dist_dir: Path,
    pattern: str,
    reject: tuple[str, ...],
    required_text: str,
) -> Path:
    matches = sorted(
        path
        for path in dist_dir.glob(pattern)
        if path.is_file() and not any(marker in path.name for marker in reject)
    )
    if required_text:
        matches = [
            path
            for path in matches
            if required_text in path.read_text(encoding="utf-8", errors="ignore")
        ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"OpenClaw internal chunk not found: {dist_dir}/{pattern}")
    names = ", ".join(path.name for path in matches)
    raise RuntimeError(f"OpenClaw internal chunk is ambiguous for {pattern}: {names}")


def _resolve_openclaw_internal_chunks() -> dict[str, Path]:
    dist_dir = _resolve_openclaw_dist_dir()
    return {
        "gateway_call": _select_single_chunk(
            dist_dir,
            "call-*.js",
            (),
            "function callGateway",
        ),
    }


def _run_openclaw_session(prompt: str) -> dict[str, Any]:
    try:
        openclaw_chunks = _resolve_openclaw_internal_chunks()
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "error": str(exc),
        }

    node_script = r'''
const prompt = process.env.OPENCLAW_LAYER1_PROMPT || '';
const waitTimeoutMs = Number(process.env.OPENCLAW_LAYER1_WRITE_RUNTIME_TIMEOUT_MS || '1800000');
const gatewayCallPath = process.env.OPENCLAW_GATEWAY_CALL_PATH;
const sessionAgentId = process.env.OPENCLAW_LAYER1_SESSION_AGENT_ID || '';

if (!sessionAgentId) {
  throw new Error('OPENCLAW_LAYER1_SESSION_AGENT_ID is required');
}

const crypto = await import('node:crypto');
const gatewayCallMod = await import(gatewayCallPath);
const callGateway = gatewayCallMod.callGateway || gatewayCallMod.r;

if (typeof callGateway !== 'function') {
  throw new Error(`callGateway is not available from OpenClaw chunk: ${gatewayCallPath}`);
}

function normalizeAgentId(agentId) {
  return String(agentId || '').trim().toLowerCase();
}

const normalizedSessionAgentId = normalizeAgentId(sessionAgentId);
const childSessionKey = `agent:${normalizedSessionAgentId}:subagent:${crypto.randomUUID()}`;
const runId = crypto.randomUUID();

const agentResult = await callGateway({
  method: 'agent',
  params: {
    message: prompt,
    sessionKey: childSessionKey,
  agentId: sessionAgentId,
    idempotencyKey: runId,
    deliver: false,
    lane: 'subagent',
    cleanupBundleMcpOnRunEnd: true,
    bootstrapContextMode: 'lightweight',
    bootstrapContextRunKind: 'default',
    label: 'MemoquasarEterna memory worker',
  },
  timeoutMs: 10000,
});

const acceptedRunId = agentResult?.runId || runId;

function getSessionsStorePath(agentId) {
  const home = process.env.HOME || process.env.USERPROFILE || '';
  const stateDir = process.env.OPENCLAW_STATE_DIR || (home ? `${home}/.openclaw` : '.openclaw');
  return `${stateDir}/agents/${normalizeAgentId(agentId)}/sessions/sessions.json`;
}

async function resolveSessionIdFromStore(agentId, sessionKey, timeoutMs) {
  const fs = await import('node:fs/promises');
  const path = getSessionsStorePath(agentId);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const raw = await fs.readFile(path, 'utf8');
      const store = JSON.parse(raw);
      const entry = store && typeof store === 'object' ? store[sessionKey] : null;
      if (entry && typeof entry === 'object') {
        const resolved = entry.sessionId || entry.session_id || entry.sessionID;
        if (resolved) {
          return String(resolved);
        }
      }
    } catch (e) {
      // ignore and retry until timeout
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return '';
}

const waitResult = await callGateway({
  method: 'agent.wait',
  params: {
    runId: acceptedRunId,
    timeoutMs: waitTimeoutMs,
  },
  timeoutMs: waitTimeoutMs + 5000,
});

const sessionId = await resolveSessionIdFromStore(sessionAgentId, childSessionKey, Math.min(waitTimeoutMs, 5000));
let waitError = null;
if (!waitResult || waitResult.status === 'timeout') {
  waitError = 'agent.wait timeout';
} else if (waitResult.status === 'error') {
  waitError = waitResult.error || 'agent.wait error';
}

console.log(JSON.stringify({
  spawnResult: agentResult,
  waitResult,
  childSessionKey,
  sessionId,
  sessionAgentId,
  waitError,
  waitSource: 'gateway-agent.wait',
}, null, 2));
'''

    env = os.environ.copy()
    env["OPENCLAW_LAYER1_PROMPT"] = _with_silent_completion_contract(prompt)
    if REQUESTER_SESSION_KEY:
        env["OPENCLAW_LAYER1_REQUESTER_SESSION_KEY"] = REQUESTER_SESSION_KEY
    env["OPENCLAW_LAYER1_WRITE_RUNTIME_TIMEOUT_MS"] = str(WAIT_TIMEOUT_MS)
    env["OPENCLAW_GATEWAY_CALL_PATH"] = str(openclaw_chunks["gateway_call"])
    env["OPENCLAW_LAYER1_SESSION_AGENT_ID"] = MEMORY_WORKER_AGENT_ID

    proc = subprocess.run(
        ["node", "--input-type=module", "-e", node_script],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
        env=env,
    )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    parsed = _parse_strict_json_stdout(stdout)

    return {
        "success": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_len": len(stdout),
        "stderr_len": len(stderr),
        "parsed": parsed,
        "parse_error": None if (not stdout.strip() or parsed is not None) else "stdout was not a single valid JSON object",
    }


def openclaw_call_subagent_readandwrite(prompt: str) -> dict[str, Any]:
    """启动 memory worker subagent，并阻塞直到 session 结束。"""
    runtime_result = _run_openclaw_session(prompt)
    parsed = runtime_result.get("parsed") or {}
    parsed_ok = isinstance(parsed, dict) and bool(parsed)
    spawn_result = parsed.get("spawnResult") if isinstance(parsed, dict) else None
    child_session_key = parsed.get("childSessionKey") if isinstance(parsed, dict) else None
    session_id = None
    if isinstance(parsed, dict):
        session_id = parsed.get("sessionId") or parsed.get("session_id")
    wait_error = parsed.get("waitError") if isinstance(parsed, dict) else None
    parse_error = runtime_result.get("parse_error")

    session_ended = runtime_result.get("success", False) and parsed_ok and not wait_error and not parse_error
    return {
        "success": session_ended,
        "session_ended": session_ended,
        "session_status": "ended" if session_ended else "running",
        "session_end_reason": None if session_ended else (wait_error or "runtime_error"),
        "agent_id": MEMORY_WORKER_AGENT_ID,
        "requester_agent_id": MEMORY_WORKER_AGENT_ID,
        "child_session_key": child_session_key,
        "session_id": session_id,
        "spawn_result": spawn_result,
        "wait_error": wait_error,
        "parse_error": parse_error,
        "runtime_result": runtime_result,
    }
