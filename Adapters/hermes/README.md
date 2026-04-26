# Adapters/hermes

## 定位

`Adapters/hermes/` 是 MemoquasarEterna 对接 Hermes profile 的 adapter。

当前 Hermes adapter 是实验性最小实现，面向 production agent，主要提供两类能力：

- `production_agents[*].agentId` 等同于 Hermes profile 名
- Layer0 extract：从 Hermes `state.db` 只读提取日级 L2
- Layer4 read：给 Hermes profile 安装一个 terminal skill，用于调用 MemoquasarEterna recall

它不支持作为 memory worker，也不实现 Hermes 侧 preserve / decay。

因此推荐的混合形态是：

```json
{
  "memory_worker_harness": "openclaw",
  "production_agents": [
    {"agentId": "hermes-init", "harness": "hermes"}
  ]
}
```

其中 `hermes-init` 必须是已经存在的 Hermes profile 名。

## 配置

运行时配置文件是：

```text
Adapters/hermes/HermesConfig.json
```

它应从模板复制：

```text
Adapters/hermes/HermesConfig-template.json
```

当前最小字段：

```json
{
  "schema_version": "1.0",
  "profiles_root": "~/.hermes/profiles",
  "state_db_name": "state.db"
}
```

字段语义：

- `profiles_root`
  - Hermes profiles 根目录，默认 `~/.hermes/profiles`
- `state_db_name`
  - 每个 profile 内的 SQLite 状态库文件名，默认 `state.db`

安装时如果 `HermesConfig.json` 不存在，`Installation/INSTALL.py` 会通过 connector 的 `ensure_config` 从模板生成。

## Layer0 Extract

Hermes extract 按 Core 传入的 memory day 窗口读取 `state.db`：

- 只取 `role in ('user', 'assistant')`
- 只取非空 `content`
- 跳过 `tool` / `session_meta`
- `message_type` 固定为 `text`
- 按 `messages.timestamp, messages.id` 稳定排序

`sessions_to_process` 当前仅用于满足 Core Layer0 既有 contract；其中的 source ref 是 `sqlite:{state_db_path}`，不代表需要读取 session 文件。

### source of truth

当前 Layer0 以 Hermes profile 的 `state.db` 为唯一 source of truth。

我们曾评估过同时读取 session JSON / JSONL / `state.db` 后再做 reconciliation，但这会显著增加跨文件 matching 的复杂度，也会让三类文件的权威性变得不清晰。因此当前实现保持简单、可维护：

- 只读 `state.db`
- 不回溯解析 Hermes session 文件
- 不尝试跨文件补齐缺失消息

### 已知限制

Hermes 的持久化时机与 OpenClaw 不同，当前观察到这些边缘情况：

- compaction 可能在 `state.db` 中产生 replay 行，需要由 adapter 过滤
- timestamp 更接近 Hermes 持久化时间，不一定等于用户客户端显示时间
- gateway stop / no-op `/compress` 等路径下，可能出现 session 文件或日志中有消息，但 `state.db` 未写入对应用户消息

因此 Hermes support 当前标记为 experimental。它适合验证 Layer0 / Layer4 方向，但还不是项目默认推荐的生产 harness。

## Layer4 Read

Hermes adapter 不把 Layer4 read 放进 connector contract，而是通过安装一个 Hermes skill 暴露读取能力：

```text
memoquasar-memory-recall
```

安装后，每个 `harness == "hermes"` 的 production agent profile 会获得：

```text
~/.hermes/profiles/{agentId}/skills/memoquasar-memory-recall/SKILL.md
```

该 skill 会通过 terminal 调用：

```bash
python Adapters/hermes/Read/memoquasar_recall.py vague --agent "{agentId}" --query "..."
python Adapters/hermes/Read/memoquasar_recall.py exact --agent "{agentId}" --date YYYY-MM-DD --window-start HH:MM --window-end HH:MM
```

其中：

- `vague`
  - 调用 `Core/Layer4_Read/ENTRY_LAYER4_vague.py`
  - 用于模糊召回、近期概览、按 query 找相关记忆
- `exact`
  - 调用 `Core/Layer4_Read/recall_L2.py`
  - 用于读取指定日期和时间窗口内的 L2 原文

## Installation

Hermes production agent 侧 install 生命周期包括：

- `ensure_config`
  - 确保 `Adapters/hermes/HermesConfig.json` 存在
- `production_agent.prerequisites`
  - 检查 Layer4 recall 入口存在
  - 检查 skill template 存在
  - 检查 `profiles_root/{agentId}` profile 目录存在
- `production_agent.install`
  - 将 `memoquasar-memory-recall` skill 渲染并写入对应 Hermes profile
- `production_agent.uninstall`
  - 删除对应 profile 下的 `memoquasar-memory-recall` skill 目录

安装过程不会改写 Hermes `state.db`，也不会创建、删除或迁移 Hermes profile 本体。

## Connector contract 覆盖情况

当前 `Adapters/hermes/CONNECTOR.py` 暴露：

- `ensure_config`
  - 已实现
- `production_agent.extract`
  - 已实现
- `production_agent.prerequisites`
  - 已实现
- `production_agent.install`
  - 已实现
- `production_agent.uninstall`
  - 已实现

当前未实现：

- `memory_worker.call_llm`
- `memory_worker.clean_runtime`
- `memory_worker.prerequisites`
- `memory_worker.install`
- `memory_worker.uninstall`
- `production_agent.preserve`
- `production_agent.decay`

如果把 `memory_worker_harness` 设为 `hermes`，Layer1 / Layer3 的 LLM 调用链不会可用。
