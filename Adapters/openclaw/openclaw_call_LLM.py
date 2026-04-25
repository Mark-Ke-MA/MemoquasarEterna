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


OPENCLAW_BUNDLE = Path("/opt/homebrew/lib/node_modules/openclaw/dist/pi-embedded-BaSvmUpW.js")
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


def _run_openclaw_session(prompt: str) -> dict[str, Any]:
    if not OPENCLAW_BUNDLE.exists():
        return {
            "success": False,
            "error": f"OpenClaw bundle not found: {OPENCLAW_BUNDLE}",
        }

    node_script = r'''
const prompt = process.env.OPENCLAW_LAYER1_PROMPT || '';
const requesterSessionKey = process.env.OPENCLAW_LAYER1_REQUESTER_SESSION_KEY || '';
const waitTimeoutMs = Number(process.env.OPENCLAW_LAYER1_WRITE_RUNTIME_TIMEOUT_MS || '1800000');
const bundlePath = process.env.OPENCLAW_BUNDLE_PATH;
const sessionAgentId = process.env.OPENCLAW_LAYER1_SESSION_AGENT_ID || '';
const requesterAgentId = sessionAgentId;

if (!sessionAgentId) {
  throw new Error('OPENCLAW_LAYER1_SESSION_AGENT_ID is required');
}

const mod = await import(bundlePath);
const spawnSubagentDirect = mod.Ps;
const waitForEmbeddedPiRunEnd = mod.l;

if (typeof spawnSubagentDirect !== 'function') {
  throw new Error('spawnSubagentDirect (Ps) is not available from OpenClaw bundle');
}
if (typeof waitForEmbeddedPiRunEnd !== 'function') {
  throw new Error('waitForEmbeddedPiRunEnd (l) is not available from OpenClaw bundle');
}

const ctx = {
  requesterAgentIdOverride: requesterAgentId,
};
if (requesterSessionKey) ctx.agentSessionKey = requesterSessionKey;

const spawnResult = await spawnSubagentDirect({
  task: prompt,
  agentId: sessionAgentId,
  mode: 'run',
  cleanup: 'keep',
  sandbox: 'inherit',
  expectsCompletionMessage: false,
}, ctx);

const childSessionKey = spawnResult?.childSessionKey || spawnResult?.sessionKey || spawnResult?.session?.key || spawnResult?.session?.sessionKey || '';

function getSessionsStorePath(agentId) {
  const home = process.env.HOME || process.env.USERPROFILE || '';
  const stateDir = process.env.OPENCLAW_STATE_DIR || (home ? `${home}/.openclaw` : '.openclaw');
  return `${stateDir}/agents/${agentId}/sessions/sessions.json`;
}

function getTranscriptLockPath(agentId, sessionId) {
  const home = process.env.HOME || process.env.USERPROFILE || '';
  const stateDir = process.env.OPENCLAW_STATE_DIR || (home ? `${home}/.openclaw` : '.openclaw');
  return `${stateDir}/agents/${agentId}/sessions/${sessionId}.jsonl.lock`;
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

async function waitForLockDisappear(lockPath, timeoutMs) {
  const fs = await import('node:fs/promises');
  const deadline = Date.now() + timeoutMs;
  let seenLock = false;
  while (Date.now() < deadline) {
    try {
      await fs.access(lockPath);
      seenLock = true;
    } catch (e) {
      if (seenLock) {
        return 'lock-gone';
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return 'lock-timeout';
}

let sessionId = '';
if (childSessionKey) {
  sessionId = await resolveSessionIdFromStore(sessionAgentId, childSessionKey, Math.min(waitTimeoutMs, 5000));
}
if (!sessionId && childSessionKey) {
  sessionId = childSessionKey.split(':').pop() || '';
}
let waitError = null;
let waitSource = '';

if (sessionId) {
  const lockPath = getTranscriptLockPath(sessionAgentId, sessionId);
  const signalPromise = waitForEmbeddedPiRunEnd(sessionId, waitTimeoutMs).then(() => 'signal-ok').catch((e) => `signal-error:${String(e && e.message ? e.message : e)}`);
  const lockPromise = waitForLockDisappear(lockPath, waitTimeoutMs).then((result) => result.startsWith('lock-') ? result : `lock-error:${result}`);
  const winner = await Promise.race([signalPromise, lockPromise]);
  waitSource = winner;
  if (winner.startsWith('signal-error:')) {
    waitError = winner.slice('signal-error:'.length);
  } else if (winner.startsWith('lock-error:')) {
    const detail = winner.slice('lock-error:'.length);
    if (detail !== 'lock-gone') {
      waitError = detail;
    }
  }
}

console.log(JSON.stringify({
  spawnResult,
  childSessionKey,
  sessionId,
  sessionAgentId,
  waitError,
  waitSource,
}, null, 2));
'''

    env = os.environ.copy()
    env["OPENCLAW_LAYER1_PROMPT"] = _with_silent_completion_contract(prompt)
    if REQUESTER_SESSION_KEY:
        env["OPENCLAW_LAYER1_REQUESTER_SESSION_KEY"] = REQUESTER_SESSION_KEY
    env["OPENCLAW_LAYER1_WRITE_RUNTIME_TIMEOUT_MS"] = str(WAIT_TIMEOUT_MS)
    env["OPENCLAW_BUNDLE_PATH"] = str(OPENCLAW_BUNDLE)
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
