# Architecture

本文档说明 MemoquasarEterna 的整体结构、memory schema、layer 协作方式，以及 adapter / connector 在其中的位置。实现细节见各 Layer README、`docs/C2_connector-contract.md`、`docs/C3_adapter-openclaw.md`、`docs/C4_adapter-hermes.md`。

## 总体结构

```text
{code_dir}/
  Core/
  Adapters/
  Installation/
  Maintenance/
  docs/
  OverallConfig-template.json
  README.md
```

| 目录 | 职责 |
| --- | --- |
| `Core/` | memory engine 本体：写入、preserve、decay、read、landmark judge |
| `Adapters/` | 外部 harness 接入层，例如 OpenClaw、Hermes |
| `Installation/` | 初始安装、配置引导、backfill、uninstall / refresh |
| `Maintenance/` | rerun、补跑、失败恢复、人工运维脚本 |
| `docs/` | 用户与维护者文档 |

核心原则：`Core/` 不直接理解外部平台，`Adapters/` 不改写 memory engine 的主职责。

## 为什么这样分层

| 目标 | 说明 |
| --- | --- |
| core 与平台分离 | 会话读取、LLM 调用、plugin 安装等平台差异由 adapter 承接 |
| 初始化与维护分离 | 首次落地看 `Installation/`，运行后修复与补跑看 `Maintenance/` |
| 仓库结构可扩展 | 新增 harness 或 Layer 功能时有稳定归属 |

## Core 内部结构

```text
Core/
  shared_funcs.py
  harness_connector.py
  Layer0_Extract/
  Layer1_Write/
  Layer2_Preserve/
  Layer3_Decay/
  Layer4_Read/
  LayerX_LandmarkJudge/
```

| 模块 | 职责 |
| --- | --- |
| `shared_funcs.py` | 配置加载、JSON 读写、标准输出等共用函数 |
| `harness_connector.py` | 加载 `Adapters/{harness}/CONNECTOR.py`，按 MW / PA 路由能力 |
| `Layer0_Extract` | harness 原始输入 -> L2 / L1 init / staging |
| `Layer1_Write` | L2 -> chunk -> Map/Reduce -> L1 -> L0 / embedding / statistics |
| `Layer2_Preserve` | active surface memory 的 archive / restore |
| `Layer3_Decay` | trim L2、shallow 聚合、deep 聚合、cleanup |
| `Layer4_Read` | vague recall / exact recall |
| `LayerX_LandmarkJudge` | 基于 statistics records 做长期统计与 landmark 判定 |

## Memory Schema: L2 / L1 / L0

| Schema | 主要作用 | 典型消费者 |
| --- | --- | --- |
| L2 | 日级原文 transcript，最高保真、最高上下文成本 | Layer1 map、Layer4 exact recall、证据回看 |
| L1 | 日级结构化总结，适合人和 LLM 阅读 | Layer4 vague recall、Layer3 decay、statistics |
| L0 | 轻量检索索引 | Layer4 query recall、embedding、关键词搜索 |

简短理解：

- L2 负责“原话是什么”
- L1 负责“这天发生了什么”
- L0 负责“这天值不值得被找回来”

### L2

路径：

```text
{store_dir}/memory/{agentId}/surface/YYYY-MM/YYYY-MM-DD_l2.json
```

核心形状：

```json
{
  "schema_version": "3.1",
  "date": "YYYY-MM-DD",
  "agent_id": "<agentId>",
  "status": "...",
  "conversation_excerpts": [
    {
      "role": "user|assistant",
      "time": "HH:MM",
      "content": "...",
      "message_type": "text",
      "turn_index": 0
    }
  ]
}
```

要点：L2 由 Layer0 归一化产生；`conversation_excerpts` 是 Layer1 chunk planning 的输入；`turn_index` 是 L1 里 `source_turns` / `emotional_peaks[].turn` 的锚点。

### L1

路径：

```text
{store_dir}/memory/{agentId}/surface/YYYY-MM/YYYY-MM-DD_l1.json
```

核心形状：

```json
{
  "success": true,
  "schema_version": "3.1",
  "date": "YYYY-MM-DD",
  "agent_id": "<agentId>",
  "status": {...},
  "generated_at": "YYYY-MM-DDTHH:MM:SSZ",
  "stats": {...},
  "memory_signal": "low|normal",
  "summary": "...",
  "tags": ["..."],
  "day_mood": "...",
  "topics": [{"name": "...", "detail": "..."}],
  "decisions": ["..."],
  "todos": ["..."],
  "key_items": [{"type": "milestone|bug_fix|config_change|decision|incident|question", "desc": "..."}],
  "emotional_peaks": [{"turn": 0, "emotion": "...", "intensity": 3, "context": "..."}],
  "_compress_hints": [0]
}
```

要点：L1 由 Layer1 Map / Reduce 生成，Stage5 写回正式 surface 文件；`memory_signal="low"` 表示当天缺乏可沉淀内容；`topics` / `decisions` / `todos` / `key_items` 是日常阅读和 vague recall 的主要材料；reduce 产生的 `source_turns` 最终写入 `_compress_hints`。

### L0

路径：

```text
{store_dir}/memory/{agentId}/surface/l0_index.json
{store_dir}/memory/{agentId}/surface/l0_embeddings.json
```

`l0_index.json`：

```json
{
  "schema_version": "3.1",
  "agent_id": "<agentId>",
  "updated_at": "YYYY-MM-DDTHH:MM:SSZ",
  "entries": [
    {
      "date": "YYYY-MM-DD",
      "summary": "...",
      "tags": ["..."],
      "mood": "...",
      "depth": "surface",
      "access_count": 0
    }
  ]
}
```

`l0_embeddings.json`：

```json
{
  "schema_version": "3.1",
  "agent_id": "<agentId>",
  "model": "<embedding_model>",
  "updated_at": "YYYY-MM-DDTHH:MM:SSZ",
  "entries": {
    "YYYY-MM-DD::surface": {
      "depth": "surface",
      "embedding": [0.0],
      "text_used": "...",
      "generated_at": "YYYY-MM-DDTHH:MM:SSZ",
      "date": "YYYY-MM-DD"
    }
  }
}
```

要点：surface L0 由 Stage6 从正式 L1 提取 `date`、`summary`、`tags`、`day_mood`；Stage7 基于 L0 构造 embedding；surface 唯一键语义是 `date + depth`，重跑同日会覆写但保留 `access_count`。

## 主链路

日级写入：

```text
harness 原始数据 -> Layer0 Extract -> L2 -> Layer1 Map/Reduce -> L1 -> Stage6/7 -> L0 / embeddings
```

长期整理：

```text
surface L2/L1/L0 -> Layer2 Preserve -> archive backup -> Layer3 Decay -> trim L2 / shallow L1 / deep L1
```

读取：

```text
query -> Layer4 -> L0 命中候选日期 -> L1 提供结构化上下文 -> 必要时 L2 提供原文证据
```

Landmark：

```text
Layer1 Stage8 statistics -> LayerX_LandmarkJudge -> Layer3 decision making
```

## Connector 与 Adapter

`Core/` 通过 `Core/harness_connector.py` 加载：

```text
Adapters/{harness}/CONNECTOR.py
```

connector contract 让 core 只关心能力名，而不关心 adapter 内部目录。当前固定接口包括：

```text
ensure_config
memory_worker.call_llm / clean_runtime / prerequisites / install / uninstall
production_agent.extract / preserve / decay / prerequisites / install / uninstall
```

当前 adapter 状态：

| Adapter | 状态 | 主要能力 |
| --- | --- | --- |
| OpenClaw | production / default | Layer0 extract、MW call_llm、runtime cleanup、Layer4 plugin、Sessions_Watch preserve / decay |
| Hermes | experimental | PA Layer0 extract、Layer4 recall skill；不提供 MW / preserve / decay |

## Installation / Maintenance / Reading

| 主题 | 入口 |
| --- | --- |
| 首次安装、配置引导、backfill、uninstall、refresh | `Installation/`、`docs/A1_installation-guide.md` |
| rerun、补跑、失败日志处理、人工维护 | `Maintenance/`、`docs/B1_maintenance-guide.md` |
| 继续理解架构与接口 | `Core/README.md`、各 Layer README、`docs/C2_connector-contract.md` |
| 继续理解 adapter | `Adapters/openclaw/README.md` / `docs/C3_adapter-openclaw.md`；`Adapters/hermes/README.md` / `docs/C4_adapter-hermes.md` |

## 一句话总结

MemoquasarEterna 以 `Core/` 为 memory engine、以 `Adapters/` 为外部接入层、以 `Installation/` 与 `Maintenance/` 组织运维脚本，并由 Layer0–4 + LayerX 分担完整记忆生命周期。
