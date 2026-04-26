# Adapters/hermes

## 定位

`Adapters/hermes/` 是 MemoquasarEterna 对接 Hermes profile 的 adapter。

第一阶段只实现 production agent 的 Layer0 extract：

- `production_agents[*].agentId` 等同于 Hermes profile 名
- 默认从 `~/.hermes/profiles/{agentId}/state.db` 只读提取
- 只读取 `sessions` 与 `messages` 表
- 不读取 `~/.hermes/sessions/` 文件
- 不实现 install / uninstall / call_LLM / preserve / decay

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

## Layer0 Extract

Hermes extract 按 Core 传入的 memory day 窗口读取 `state.db`：

- 只取 `role in ('user', 'assistant')`
- 只取非空 `content`
- 跳过 `tool` / `session_meta`
- `message_type` 固定为 `text`
- 按 `messages.timestamp, messages.id` 稳定排序

`sessions_to_process` 当前仅用于满足 Core Layer0 既有 contract；其中的 source ref 是 `sqlite:{state_db_path}`，不代表需要读取 session 文件。
