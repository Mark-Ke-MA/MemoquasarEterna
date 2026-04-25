# Layer2_Preserve

## 这一层做什么

`Layer2_Preserve/` 是 **MemoquasarEterna** 中负责 **surface 层周级 preserve** 的层。

它的职责不是生成每日记忆，也不是做长期衰减或读取，而是把已经存在于 `memory/.../surface` 的表层记忆，按周归档成可审计的 archive 包。

Layer2 当前的稳定主线是：

- 按 ISO week 收集 surface 层对象
- 生成周级 archive 包
- 抽取并打包对应的 surface `l0_index` / `l0_embeddings` 子集
- archive 成功后回写 `l1/l2.status.archived = true`
- 写 preserve 审计日志

---

## 输入

Layer2 的输入主要来自三部分：

### 1. Active surface memory

Layer2 archive 直接读取：

- `memory/{agentId}/surface/...` 下的 `*_l1.json`
- `memory/{agentId}/surface/...` 下的 `*_l2.json`
- `.nocontent`
- `.noconversation`
- `memory/{agentId}/surface/l0_index.json`
- `memory/{agentId}/surface/l0_embeddings.json`

也就是说，Layer2 处理的对象已经是 Layer1 生成完成的 active surface 数据。

### 2. 总配置

Layer2 读取 `OverallConfig.json` 中与以下内容相关的字段：

- `archive_dir`
- `archive_dir_structure`
- `store_dir`
- `store_dir_structure`
- `production_agents`

### 3. Harness connector

Layer2 通过固定 connector 接口使用 harness 能力：

- `production_agent.preserve`（可选）

若该接口存在，则会在 archive 主链入口的固定位置调用；若不存在，则静默跳过。

---

## 输出

Layer2 archive 的核心输出包括：

### 1. 周级 archive 包

路径约定为：

```text
{archive_dir}/core/{agentId}/{week_id}.tar.gz
```

archive 包内当前固定包含：

- `manifest.json`
- `l0_index_entries.json`
- `l0_embeddings_entries.json`
- 该周命中的 `*_l1.json`
- 该周命中的 `*_l2.json`
- 该周命中的 `.nocontent`
- 该周命中的 `.noconversation`

### 2. Active 文件状态回写

archive 成功后，Layer2 会对成功归档的 `l1/l2` 回写：

- `status.archived = true`
- `status.archived_at = ...`

### 3. Preserve 审计日志

日志路径来自 `store_dir_structure.logs.layer2_preserve` 的配置约定。

Layer2 不采用“只记失败”的策略，而是保留 run-level preserve 摘要日志。

---

## 主入口

### `ENTRY_LAYER2_archive.py`

这是 Layer2 archive 的统一入口。

它支持：

- 默认全流水线运行
- 单阶段运行
- `harness-only`
- `core-only`
- `dry-run`

常见示例：

```bash
python3 ENTRY_LAYER2_archive.py --week <YYYY-WXX>
```

只处理指定 agent：

```bash
python3 ENTRY_LAYER2_archive.py --week <YYYY-WXX> --agent <agent_id>
```

只运行单个阶段：

```bash
python3 ENTRY_LAYER2_archive.py --week <YYYY-WXX> --Stage Stage2
```

只执行 harness 侧 preserve 逻辑：

```bash
python3 ENTRY_LAYER2_archive.py --week <YYYY-WXX> --harness-only
```

---

## 内部结构

Layer2 archive 当前由 3 个 stage 构成。

### Stage1 — List files

- 解析目标 ISO week
- 收集本周 candidate files
- 构建 archive plan
- 记录每个 agent 的：
  - `window_start`
  - `window_end`
  - `candidate_files`
  - `l0_index_path`
  - `l0_embeddings_path`
  - `archive_path`

### Stage2 — Archive

- 根据 Stage1 plan 生成周级 `tar.gz`
- 打包命中的 surface `l1/l2/marker` 文件
- 抽取该周对应的 surface `l0_index` subset
- 抽取该周对应的 surface `l0_embeddings` subset
- 写入 `manifest.json`

### Stage3 — Finalize

- 对成功 archive 的 `l1/l2` 回写 archived 状态
- 写 preserve log
- 保留 skip / partial / failed 的最小摘要

---

## Archive contract

### 物理路径

archive 包当前固定写到：

```text
{archive_dir}/core/{agentId}/{week_id}.tar.gz
```

### 包内结构

当前约定：

- 只处理 `surface`
- tar 包内部平铺
- 不保留 `YYYY-MM/` 目录层
- 文件名沿用 store 中现有日期命名

### 默认行为

- 默认不覆盖已存在周包
- 只有显式 `--overwrite` 时才允许覆盖
- archive 阶段不会删除 active 原文件

---

## 日志

Layer2 preserve 当前保留 run-level 审计日志。

日志通常包括：

- `schema_version`
- `created_at`
- `window_start`
- `window_end`
- `success`
- `agents[]`

每个 agent 通常包括：

- `agent_id`
- `status`
- `archive_path`
- `updated_files`
- `reason`

日志不记录正文内容。

---

## 角色边界

Layer2 聚焦于 surface 层的 preserve、archive 与 restore。

围绕它的其他职责分布为：

- Layer1_Write：生成日级记忆与表层写入结果
- Layer3_Decay：处理 shallow / deep 衰减
- Layer4_Read：处理 recall / read
- Layer0 / Layer1：完成输入提取与写入链路中的总结与结构生成

---

## 与其他层的关系

### 向上游

Layer2 直接承接：

- Layer1 已生成完成的 active surface memory

### 向下游

Layer2 的 archive 结果主要服务于：

- 作为 surface 层的周级备份与审计对象
- 为更长期的数据生命周期管理提供可恢复归档

它在整个产品中为 Layer3 与 Layer4 提供稳定的 surface 归档前提与可恢复对象。

因此 Layer2 在整个产品中的位置是：

> 为 active surface memory 提供周级 preserve 能力，并把“已经写成的表层记忆”变成可审计、可归档的稳定对象。
