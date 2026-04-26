# Hermes Adapter

本文档说明 `Adapters/hermes/` 的当前能力边界。Hermes adapter 是 experimental adapter，不是默认 production harness。

## 当前定位

Hermes adapter 只面向 production agent，提供两条最小链路：

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Layer0 extract | yes | 从 Hermes profile 的 `state.db` 生成 MemoquasarEterna L2 |
| Layer4 read | yes | 给 Hermes profile 安装 recall skill |
| memory worker | no | 不提供 `call_llm` / runtime cleanup / MW install |
| preserve / decay | no | 不处理 Hermes 侧长期状态整理 |

推荐组合：

```json
{
  "memory_worker_harness": "openclaw",
  "production_agents": [
    {"agentId": "hermes-init", "harness": "hermes"}
  ]
}
```

## agentId 与 profile

在 Hermes adapter 中：

```text
production_agents[*].agentId == Hermes profile name
```

例如 `agentId = "hermes-init"` 对应：

```text
~/.hermes/profiles/hermes-init/
```

当前不提供额外映射层，以减少配置复杂度。

## 配置

```text
Adapters/hermes/HermesConfig.json
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

`INSTALL.py` 会通过 connector 顶层 `ensure_config` 自动生成缺失的 `HermesConfig.json`。

## Layer0 extract

默认读取：

```text
~/.hermes/profiles/{agentId}/state.db
```

归一化规则：

- 只保留 `user` / `assistant`
- 跳过 `tool` / `session_meta`
- 跳过空内容
- `message_type` 固定为 `text`
- 按 `messages.timestamp, messages.id` 稳定排序

`sessions_to_process` 中的 source ref 写成 `sqlite:{state_db_path}`，只是满足 Core Layer0 既有 contract；adapter 不继续读取 session JSON / JSONL。

## Source of Truth 与限制

当前以 `state.db` 为唯一 source of truth。我们评估过同时读取 `state.db`、session JSON、session JSONL，但三源 reconciliation 会引入跨文件 matching、冲突解决与优先级规则，维护成本高于收益。

已知限制：

- compaction 可能在 `state.db` 里产生 replay 行，需要过滤
- timestamp 更接近 Hermes 持久化时间，不一定等于客户端显示时间
- gateway stop / no-op `/compress` 等路径下，可能出现 session 文件或日志有消息，但 `state.db` 没有对应用户消息

因此 Hermes 当前适合验证 Layer0 / Layer4 接入，不建议替代 OpenClaw 作为默认生产方案。

## Layer4 recall skill

安装 skill：

```text
~/.hermes/profiles/{agentId}/skills/memoquasar-memory-recall/SKILL.md
```

skill 调用入口：

```bash
python Adapters/hermes/Read/memoquasar_recall.py vague --agent "{agentId}" --query "..."
python Adapters/hermes/Read/memoquasar_recall.py exact --agent "{agentId}" --date YYYY-MM-DD --window-start HH:MM --window-end HH:MM
```

| mode | 用途 |
| --- | --- |
| `vague` | 模糊召回、近期概览、query 相关记忆 |
| `exact` | 读取指定日期和时间窗口的 L2 原文 |

Layer4 read 不进入 connector contract；它仍由 `Core/Layer4_Read/` 提供，Hermes adapter 只负责包装成 Hermes skill。

## Installation 生命周期

| 接口 | 行为 |
| --- | --- |
| `ensure_config` | 确保 `HermesConfig.json` 存在 |
| `production_agent.prerequisites` | 检查 recall 入口、skill template、profile 目录 |
| `production_agent.install` | 渲染并写入 `memoquasar-memory-recall/SKILL.md` |
| `production_agent.uninstall` | 删除 profile 下的 `memoquasar-memory-recall/` |

安装和卸载不会改写 Hermes `state.db`，也不会删除 Hermes profile。

## 未实现接口

```text
memory_worker.call_llm
memory_worker.clean_runtime
memory_worker.prerequisites / install / uninstall
production_agent.preserve
production_agent.decay
```

因此不要把：

```json
"memory_worker_harness": "hermes"
```

作为生产配置使用。

## 一句话总结

Hermes adapter 当前是最小 experimental PA adapter：它能把 Hermes `state.db` 写入 MemoquasarEterna，并给 Hermes profile 安装 Layer4 recall skill，但不承担 MW、preserve 或 decay。
