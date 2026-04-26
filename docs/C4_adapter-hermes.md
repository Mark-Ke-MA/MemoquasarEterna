# Hermes Adapter

## 文档目标

本文档说明 `Adapters/hermes/` 的当前能力边界。

Hermes adapter 目前是 experimental adapter，不是默认生产 harness。它的目标是让 Hermes production agent 能接入 MemoquasarEterna 的两条最小链路：

- Layer0 extract：从 Hermes profile 的 `state.db` 生成 MemoquasarEterna L2
- Layer4 read：通过 Hermes skill 调用 MemoquasarEterna recall

它当前不承担 memory worker，也不承担 Hermes 侧 preserve / decay。

---

## agentId 与 Hermes profile

在 Hermes adapter 中：

```text
production_agents[*].agentId == Hermes profile name
```

例如：

```json
{
  "production_agents": [
    {"agentId": "hermes-init", "harness": "hermes"}
  ]
}
```

对应的 Hermes profile 目录应为：

```text
~/.hermes/profiles/hermes-init/
```

当前不提供 agentId 与 profile 的额外映射层。这样做是为了减少配置复杂度，也符合 Hermes profile 本身承载 agent 人格的语义。

---

## 配置文件

Hermes adapter 使用：

```text
Adapters/hermes/HermesConfig.json
```

仓库跟踪模板：

```text
Adapters/hermes/HermesConfig-template.json
```

当前字段：

```json
{
  "schema_version": "1.0",
  "profiles_root": "~/.hermes/profiles",
  "state_db_name": "state.db"
}
```

`Installation/INSTALL.py` 会通过 connector 顶层 `ensure_config` 自动生成缺失的 `HermesConfig.json`。

---

## Layer0 extract

Hermes Layer0 extract 读取：

```text
{profiles_root}/{agentId}/{state_db_name}
```

默认等价于：

```text
~/.hermes/profiles/{agentId}/state.db
```

当前只读取 SQLite 中与会话消息相关的记录，并归一化为 Core Layer0 可消费的 L2 输入：

- 只保留 `user` / `assistant`
- 跳过 `tool` / `session_meta`
- 跳过空内容
- `message_type` 固定为 `text`
- 按 `messages.timestamp, messages.id` 稳定排序

`sessions_to_process` 中的 source ref 会写成 `sqlite:{state_db_path}`，只是为了满足 Core Layer0 既有 contract，不表示 adapter 会继续读取 session JSON / JSONL 文件。

---

## state.db source of truth

Hermes adapter 当前以 `state.db` 为唯一 source of truth。

原因是三源合并会引入较高复杂度：

- `state.db`
- session JSON
- session JSONL

如果同时读取三类文件，就必须设计跨文件消息 matching、冲突解决与优先级规则。考虑到当前 Hermes adapter 只做最小接入，这种 reconciliation 的维护成本大于收益。

---

## 已知限制

Hermes 与 OpenClaw 的持久化时机不同。当前观察到：

- compaction 可能在 `state.db` 里产生 replay 行
- timestamp 更接近 Hermes 持久化时间，不一定等于用户客户端显示时间
- gateway stop / no-op `/compress` 等路径下，可能出现 session 文件或日志里有消息，但 `state.db` 没有对应用户消息

因此当前 Hermes Layer0 更适合作为实验性接入，而不是替代 OpenClaw 的生产默认方案。

---

## Layer4 read skill

Hermes adapter 通过安装 Hermes skill 暴露 Layer4 recall：

```text
memoquasar-memory-recall
```

安装目标：

```text
~/.hermes/profiles/{agentId}/skills/memoquasar-memory-recall/SKILL.md
```

该 skill 会调用：

```bash
python Adapters/hermes/Read/memoquasar_recall.py vague --agent "{agentId}" --query "..."
python Adapters/hermes/Read/memoquasar_recall.py exact --agent "{agentId}" --date YYYY-MM-DD --window-start HH:MM --window-end HH:MM
```

其中：

- `vague`
  - 用于模糊召回、近期概览、query 相关记忆
- `exact`
  - 用于读取特定日期和时间窗口的 L2 原文

Layer4 read 不进入 connector contract。它仍由 `Core/Layer4_Read/` 提供，Hermes adapter 只负责把它包装成 Hermes 可调用的 skill。

---

## Installation 生命周期

Hermes production agent 侧实现了：

- `ensure_config`
- `production_agent.prerequisites`
- `production_agent.install`
- `production_agent.uninstall`

### prerequisites

检查：

- `Adapters/hermes/Read/memoquasar_recall.py` 存在
- `memoquasar-memory-recall` skill template 存在
- 每个 Hermes production agent 对应的 profile 目录存在

### install

对每个 `harness == "hermes"` 的 production agent：

- 渲染 skill template
- 写入 profile 的 `skills/memoquasar-memory-recall/SKILL.md`

### uninstall

对每个 `harness == "hermes"` 的 production agent：

- 删除 profile 下的 `skills/memoquasar-memory-recall/`

安装和卸载都不会改写 Hermes `state.db`，也不会删除 Hermes profile。

---

## 未实现能力

当前 Hermes adapter 不实现：

- `memory_worker.call_llm`
- `memory_worker.clean_runtime`
- `memory_worker.prerequisites`
- `memory_worker.install`
- `memory_worker.uninstall`
- `production_agent.preserve`
- `production_agent.decay`

因此不应把：

```json
"memory_worker_harness": "hermes"
```

作为生产配置使用。

---

## 推荐使用方式

当前推荐：

- OpenClaw 继续作为 memory worker harness
- Hermes 只作为 experimental production agent harness
- 用 Hermes adapter 验证 Layer0 / Layer4 接入
- 不依赖 Hermes adapter 执行 Layer2 / Layer3 的平台侧 preserve / decay

这也是当前最小实现的设计边界。
