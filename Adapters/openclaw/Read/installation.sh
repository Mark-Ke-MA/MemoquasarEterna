#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
OVERALL_CONFIG_PATH="${REPO_ROOT}/OverallConfig.json"
EXTENSIONS_ROOT="${OPENCLAW_EXTENSIONS_PATH:-$HOME/.openclaw/extensions}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -f "${OVERALL_CONFIG_PATH}" ]]; then
  echo "ERROR: OverallConfig.json not found at: ${OVERALL_CONFIG_PATH}" >&2
  exit 1
fi

CONFIG_JSON="$(${PYTHON_BIN} - <<'PY' "${OVERALL_CONFIG_PATH}"
import json, sys
from pathlib import Path
cfg = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
product_name = cfg.get('product_name')
if not isinstance(product_name, str) or not product_name.strip():
    raise SystemExit('ERROR: OverallConfig.json.product_name is missing or invalid')
agent_ids = cfg.get('agentId_list')
if not isinstance(agent_ids, list) or not all(isinstance(x, str) and x.strip() for x in agent_ids):
    raise SystemExit('ERROR: OverallConfig.json.agentId_list is missing or invalid')
plugin_name = product_name.strip()
plugin_id = ''.join(ch.lower() if ch.isalnum() else '_' for ch in plugin_name).strip('_') or 'clean_memory_read'
print(json.dumps({
    'product_name': plugin_name,
    'plugin_name': plugin_name,
    'plugin_id': plugin_id,
    'agent_id_list': agent_ids,
}, ensure_ascii=False))
PY
)"

PLUGIN_NAME="$(${PYTHON_BIN} - <<'PY' "${CONFIG_JSON}"
import json, sys
print(json.loads(sys.argv[1])['plugin_name'])
PY
)"
PLUGIN_ID="$(${PYTHON_BIN} - <<'PY' "${CONFIG_JSON}"
import json, sys
print(json.loads(sys.argv[1])['plugin_id'])
PY
)"
AGENT_ID_LIST_JSON="$(${PYTHON_BIN} - <<'PY' "${CONFIG_JSON}"
import json, sys
print(json.dumps(json.loads(sys.argv[1])['agent_id_list'], ensure_ascii=False))
PY
)"
TARGET_DIR="${EXTENSIONS_ROOT}/${PLUGIN_ID}"

mkdir -p "${TARGET_DIR}"

INDEX_TEMPLATE="${SCRIPT_DIR}/index.ts.template"
MANIFEST_TEMPLATE="${SCRIPT_DIR}/openclaw.plugin.json.template"
SKILLS_SOURCE_DIR="${SCRIPT_DIR}/skills"
INDEX_TARGET="${TARGET_DIR}/index.ts"
MANIFEST_TARGET="${TARGET_DIR}/openclaw.plugin.json"
SKILLS_TARGET_DIR="${TARGET_DIR}/skills"

if [[ ! -f "${INDEX_TEMPLATE}" || ! -f "${MANIFEST_TEMPLATE}" ]]; then
  echo "ERROR: template files are missing under ${SCRIPT_DIR}" >&2
  exit 1
fi

if [[ ! -d "${SKILLS_SOURCE_DIR}" ]]; then
  echo "ERROR: skills directory is missing under ${SCRIPT_DIR}" >&2
  exit 1
fi

${PYTHON_BIN} - <<'PY' "${INDEX_TEMPLATE}" "${INDEX_TARGET}" "${MANIFEST_TEMPLATE}" "${MANIFEST_TARGET}" "${PYTHON_BIN}" "${REPO_ROOT}" "${PLUGIN_ID}" "${PLUGIN_NAME}" "${AGENT_ID_LIST_JSON}"
import sys
from pathlib import Path

index_tpl, index_out, manifest_tpl, manifest_out, python_bin, repo_root, plugin_id, plugin_name, agent_id_list_json = sys.argv[1:10]

replacements = {
    '__PYTHON_BIN__': python_bin,
    '__REPO_ROOT__': repo_root,
    '__PLUGIN_ID__': plugin_id,
    '__PLUGIN_NAME__': plugin_name,
    '__AGENT_ID_LIST__': agent_id_list_json,
}

for src, dst in [(index_tpl, index_out), (manifest_tpl, manifest_out)]:
    text = Path(src).read_text(encoding='utf-8')
    for old, new in replacements.items():
        text = text.replace(old, new)
    Path(dst).write_text(text, encoding='utf-8')
PY

rm -rf "${SKILLS_TARGET_DIR}"
mkdir -p "${SKILLS_TARGET_DIR}"
cp -R "${SKILLS_SOURCE_DIR}/." "${SKILLS_TARGET_DIR}/"

cat <<EOF
Installed OpenClaw extension to:
  ${TARGET_DIR}

Manual next steps:
1. Update ~/.openclaw/openclaw.json so the target agent(s) allow this plugin and/or its tool names.
   Recommended examples:
   - add plugin id: ${PLUGIN_ID}
   - add tool names like: <agent_id>_memory_vague_recall / <agent_id>_memory_exact_recall
2. Optionally set plugins.allow to an explicit trusted list including: ${PLUGIN_ID}
3. Restart OpenClaw gateway.
4. Verify with:
   openclaw plugins inspect ${PLUGIN_ID}

If you later move the clean memory code directory, update this line in:
  ${TARGET_DIR}/index.ts

  const REPO_ROOT = "...";

Then restart OpenClaw gateway again.
EOF
