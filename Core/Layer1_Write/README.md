# Layer1_Write

## 这一层做什么

`Layer1_Write/` 是 **MemoquasarEterna** 中负责**日级记忆写入主流水线**的层。

它的职责不是做长期存储、衰减或读取，而是把某一天的原始对话，从 Layer0 的提取结果开始，经过 chunk 规划、Map / Reduce、正式写回、索引更新、embedding 更新与收尾清理，变成一条完整、可追踪、可失败收口的写入链路。

---

## 输入

Layer1 的输入主要来自三部分：

### 1. Layer0 产物

Layer1 直接消费 Layer0 生成的：

- surface `L2`
- surface `L1` 初始化文件
- staging `extraction_ready.json`

其中真正驱动 Stage2 之后流程的关键输入，是 staging 中间产物。

### 2. 总配置

Layer1 会读取 `OverallConfig.json` 中与以下内容相关的字段：

- `store_dir`
- `store_dir_structure`
- `nprl_llm_max`
- `layer1_write`
- `use_embedding`
- `embedding_model`
- `embedding_api_url`
- `window`

### 3. Harness connector

Layer1 通过固定 connector 接口使用 harness 能力：

- `memory_worker.call_llm`（必选）
- `memory_worker.clean_runtime`（可选）

其中：

- `memory_worker.call_llm` 用于 Stage3 与 Stage4 的语义处理
- `memory_worker.clean_runtime` 若存在，则在 Stage1 与 Layer3 Phase0 等固定位置调用

---

## 输出

Layer1 的核心输出包括：

### 1. 正式 surface L1

路径：

```text
{store_dir}/memory/{agentId}/surface/YYYY-MM/YYYY-MM-DD_l1.json
```

内容：

- 当天结构化记忆摘要
- `memory_signal`
- `summary`
- `tags`
- `day_mood`
- `topics`
- `decisions`
- `todos`
- `key_items`
- `emotional_peaks`
- status 与 stats

### 2. Surface L0 索引

路径：

```text
{store_dir}/memory/{agentId}/surface/l0_index.json
```

内容：

- 面向后续检索与衰减流程的 surface 索引项

### 3. Surface embedding 索引

路径：

```text
{store_dir}/memory/{agentId}/surface/l0_embeddings.json
```

内容：

- 基于 `l0_index.json` 生成的 embedding entries

### 4. Landmark 原始统计 records

路径：

```text
{store_dir}/statistics/landmark_scores/{agentId}_landmark_scores.json
```

内容：

- 供后续 Landmark 判定使用的日级原始统计记录

### 5. Failed log 与 staging 清理结果

路径来自 `store_dir_structure.logs.layer1_write` 的配置约定。

Layer1 只在检测到失败或 skip 条件时写 failed log；正常运行不会生成成功摘要日志。

---

## 主入口

### `ENTRY_LAYER1.py`

这是 Layer1 的统一入口。

它支持：

- 默认全流水线运行
- 单阶段运行
- 多阶段串行运行

常见示例：

```bash
python3 ENTRY_LAYER1.py --date <YYYY-MM-DD>
```

只运行单个阶段：

```bash
python3 ENTRY_LAYER1.py --date <YYYY-MM-DD> --Stage Stage4
```

运行多个阶段：

```bash
python3 ENTRY_LAYER1.py --date <YYYY-MM-DD> --Stage Stage1,Stage2,Stage8
```

只对指定 agent 运行：

```bash
python3 ENTRY_LAYER1.py --date <YYYY-MM-DD> --agent <agent_id>
```

---

## 内部结构

Layer1 当前由 9 个 stage 构成。

### Stage1 — 调用 Layer0，并初始化 plan

- 调用 `ENTRY_LAYER0.py`
- 初始化 `plan.json`
- 若 `memory_worker.clean_runtime` 存在，则先执行对应的 worker runtime 清理逻辑
- 处理无对话与极低信息日的早停分支
- 支持仅写 staging 的模式

### Stage2 — Chunk planning

- 读取 `extraction_ready.json`
- 进行 chunk 切分
- 预填 Stage3–9 所需 contract

### Stage3 — Map dispatch

- 对每个 chunk 调用 `call_llm`
- 验收 Map 输出
- 执行 retry
- 对失败 agent 剪裁后续任务

### Stage4 — Reduce dispatch

- 对单日多个 chunk 的中间结果调用 `call_llm`
- 验收 `reduced_results.json`
- 执行 retry
- 对失败 agent 剪裁后续任务

### Stage5 — Finalize

- 把 reduce 结果正式写回 surface L1
- 处理 `memory_signal=normal|low`
- 若为 `low`，会创建 `.nocontent` 并同步移除后续任务

### Stage6 — Index update

- 从正式 L1 更新 `l0_index.json`

### Stage7 — Embedding update

- 从 `l0_index.json` 生成 embedding 文本
- 调用 embedding 服务
- 写入 `l0_embeddings.json`
- 支持 `use_embedding=false` 或 embedding 服务不可用时整体 skip

### Stage8 — Record scores

- 从正式 L1 提取 landmark 原始统计
- 写入 `statistics/landmark_scores/`

### Stage9 — Cleanup

- 根据 `plan.json` 汇总异常状态
- 必要时写 failed log
- 清理 `staging/staging_surface/{agentId}/` 下的临时文件
- 不清理 `plan.json`

---

## plan.json 的角色

Layer1 当前把 `plan.json` 当作**单向推进的运行状态机**来使用。

核心原则是：

- 每个 stage 只读取自己所需的输入字段与前置结果字段
- 每个 stage 只改写自己以及下游会消费的字段

也就是说，`plan.json` 在 Layer1 中承担的是：

- 运行时 contract
- 阶段推进记录
- 失败剪裁依据
- 收尾清理依据

它更适合作为运行时状态与阶段推进记录来理解。

---

## Failed log

Stage9 支持根据 `plan.json` 中的异常状态写入 failed log。

### 触发条件

只要关键 stage 出现失败或 skip 条件，就会写 failed log。

### 内容原则

failed log 只记录异常，不记录正常运行摘要。

当前主要用于记录：

- 目标日期
- 出错 stage
- failed agents
- failed chunks
- skip 信息

它的目标是：

- 便于后续按日期查漏补缺
- 便于批处理或 backfill 场景统一补跑

---

## 统计 records

Stage8 会把 Landmark 判定所需的原始统计写入：

```text
{store_dir}/statistics/landmark_scores/{agentId}_landmark_scores.json
```

这些 records 的定位是：

- 作为后续 Landmark 判定的长期统计底座
- 服务于后续 LayerX 的判定与分析消费
- 允许对同一天记录进行覆盖写入

---

## 清理逻辑

Stage9 的清理原则是：

- 只清理 `staging/staging_surface/{agentId}/` 下的内容
- 保留 agent 目录本身
- 不清理 `plan.json`
- 不碰 `memory/`、`logs/`、`statistics/` 等其他区域

清理采用保守策略：

- 若目标 staging 目录不存在或不是目录，则 Stage9 失败
- 不自动创建缺失目录后再清理

---

## 入口参数

`ENTRY_LAYER1.py` 当前支持的主要参数包括：

- `--date`
- `--Stage StageX`
- `--agent`
- `--dry-run`
- `--show-plan`
- `--stage1-staging-only`
- `--run-mode auto|manual`
- `--run-name`
- `--output_mode print|write`
- `--output_write_path`

其中：

- `--Stage` 支持单阶段与逗号分隔的多阶段模式
- `--agent` 支持单 agent 与逗号分隔的多 agent 模式
- `--output_mode write` 适合外层 orchestration 脚本消费 Layer1 结果，避免 stdout 噪音

---

## 角色边界

Layer1 聚焦于“日级记忆写入主流水线”本身。

围绕它的其他职责分布为：

- Layer3_Decay：处理长期记忆衰减与合并
- Layer4_Read：处理读取层的上下文召回
- Installation：承载初始化与初始 backfill 脚本
- Adapters：承载具体 harness runtime 与平台接入

---

## 与其他层的关系

### 向上游

Layer1 直接承接：

- Layer0 的提取结果

### 向下游

Layer1 的正式输出会被后续层消费：

- Layer2_Preserve 会处理 surface 层归档
- Layer3_Decay 会消费 surface / shallow / deep 层数据继续衰减与合并
- Layer4_Read 会通过 L0 / L1 / L2 结构执行读取与召回

因此 Layer1 在整个产品中的位置是：

> 把原始对话稳定地写成可长期保存、可继续衰减、可继续读取的表层记忆。
