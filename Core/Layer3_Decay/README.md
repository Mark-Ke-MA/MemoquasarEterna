# Layer3_Decay

## 这一层做什么

`Layer3_Decay/` 是 **MemoquasarEterna** 中负责 **多层级记忆衰减** 的层。

它的职责不是生成新记忆，而是在 Preserve 已建立安全副本的前提下，按时间层级与风险层级，对 active memory 与相关 harness-side runtime 数据做逐层减薄，控制长期膨胀速度。

一句话说：

> Layer2 负责先保住，Layer3 负责再减薄。

---

## 输入

Layer3 的输入主要来自三部分：

### 1. Active memory

Layer3 会消费：

- surface 层 active memory
- shallow 层聚合结果
- deep 层聚合结果
- `l0_index.json`
- `l0_embeddings.json`

其中不同 phase 使用的时间层级不同：

- Phase1 处理 surface `L2`
- Phase2 把周级 surface 压缩成 shallow
- Phase3 把多周 shallow 压缩成 deep

### 2. 总配置

Layer3 读取 `OverallConfig.json` 中与以下内容相关的字段：

- `store_dir`
- `store_dir_structure`
- `archive_dir`
- `layer3_decay`
- `timezone`
- `harness`

### 3. Harness connector

Layer3 通过固定 connector 接口使用 harness 能力：

- `call_llm`（必选）
- `harness_clean`（可选）
- `harness_decay`（可选）

其中：

- `call_llm` 由 Phase2 / Phase3 的 reduce 阶段使用
- `harness_clean` 在 Phase0 的固定位置调用
- `harness_decay` 在 Phase4 的固定位置调用

---

## 输出

Layer3 的核心输出包括：

### 1. Trimmed surface L2

Phase1 会对较旧的 archived surface `L2` 做瘦身处理，降低 active surface 的长期体积。

### 2. Shallow memory

路径约定为：

```text
{store_dir}/memory/{agentId}/shallow/{YYYY-WXX}.json
```

它表示对单周 surface memory 的周级压缩结果。

### 3. Deep memory

路径约定为：

```text
{store_dir}/memory/{agentId}/deep/{window}.json
```

它表示对多周 shallow 的进一步深层聚合结果。

### 4. 更新后的 L0 索引与 embedding

Phase2 / Phase3 在生成 shallow / deep 后，会同步更新：

- `l0_index.json`
- `l0_embeddings.json`

当前 L0 已是 mixed-depth 索引层，包含：

- `surface`
- `shallow`
- `deep`

### 5. Layer3 failed log

顶层 `ENTRY_LAYER3.py` 在非 dry-run 且某个 phase 失败时，会写 Layer3 failed log，便于自动任务或 backfill 场景统一补跑。

---

## 主入口

### `ENTRY_LAYER3.py`

这是 Layer3 的统一入口。

它支持：

- 默认完整链路运行
- 按 phase 运行
- 各 phase 内部的 stage 透传

常见示例：

```bash
python3 ENTRY_LAYER3.py
```

只运行某个 phase：

```bash
python3 ENTRY_LAYER3.py --Phase Phase2
```

给某个 phase 透传 stage：

```bash
python3 ENTRY_LAYER3.py --Phase Phase2 --Stage Stage3
```

只处理指定 agent：

```bash
python3 ENTRY_LAYER3.py --Phase Phase2 --agent <agent_id>
```

---

## 顶层规则

### 1. 默认不传 `--Phase`

顶层会顺序执行：

- `Phase0`
- `Phase1`
- `Phase2`
- `Phase3`
- `Phase4`

### 2. 顶层不解释 `--Stage`

`Stage` 是 phase 内部语义。

因此：

- 若传 `--Stage`
- 必须同时传 `--Phase`

顶层只透传，不做额外解释。

### 3. `--apply_cleanup`

当前主要影响：

- `Phase2`
- `Phase3`
- `Phase4`

它用于控制真正的 destructive cleanup 是否执行。

### 4. `--run-mode / --run-name`

当前主要由 `Phase0` 使用，并透传给 Layer2 preserve 统一入口。

---

## 内部结构

Layer3 当前采用 **Phase > Stage** 结构，共分为 5 个 phase。

### Phase0 — Core archive wrapper

职责：

- 在真正进入 decay 前，先触发 Layer2 preserve
- 调用 `harness_clean`（如果存在）
- 调用 Layer2 archive 主链

它是 Layer3 的安全前置阶段。

### Phase1 — Trim L2

职责：

- 对较旧、且已 archive-confirmed 的 surface `L2` 做瘦身
- 保留必要对话信息
- 控制 active surface `L2` 的长期体积

### Phase2 — Shallow

职责：

- 将单周 surface memory 压缩成一个 shallow 周文件
- 删除进入删除候选的 non-landmark surface 文件
- 更新 shallow 对应的 `l0_index` / `l0_embeddings`

### Phase3 — Deep

职责：

- 当 shallow weeks 累积到门槛时，消费最老的一批 shallow
- 生成 deep window
- 删除被消费的 shallow 文件与对应 shallow L0 条目
- 更新 deep 对应的 `l0_index` / `l0_embeddings`

### Phase4 — Harness-side decay

职责：

- 承接 Layer3 中唯一允许的 harness-specific decay 行为
- 调用 `harness_decay`（如果存在）

当前它用于把 harness-side runtime/watch 相关的衰减逻辑与 core memory decay 分离。

---

## 时间层级设计

Layer3 当前的核心思想是：

- 不同年龄段的数据
- 用不同层级表示
- 用不同风险级别的删除动作处理

### Surface

最近的 active memory 仍保持 surface 形态。

### Shallow

当某一整周的 surface 进入 shallow 条件后，会被压缩为：

- `shallow/{YYYY-WXX}.json`

### Deep

当 shallow weeks 累积达到 `deep_max_shallow` 门槛后，会进一步压缩为：

- `deep/{window}.json`

也就是说，Layer3 的目标不是删除信息本身，而是：

> 用越来越稀疏、越来越长时间尺度的表示形式，继续保存可读记忆。

---

## 设计原则

### 1. Preserve 永远先于 Decay

这是 Layer3 最重要的安全边界。

即：

- 先 archive / preserve
- 再 trim / shallow / deep / harness-side decay

任何 destructive cleanup 都建立在“副本已存在”的前提上。

### 2. Core decay 与 harness decay 分离

Layer3 当前只允许：

- core memory decay 放在 Phase0–3
- harness-side decay 放在 Phase4

这样可以避免把 harness 逻辑混进 core 衰减主链。

### 3. Cleanup 与生成逻辑解耦

- 中间阶段负责生成新层结果
- cleanup 阶段负责删除候选对象
- 删除候选由 planning contract 明确给出
- 不依赖 prompt 内部临时状态

### 4. 危险删除必须显式受控

当前主要控制手段包括：

- `--apply_cleanup`
- archive-confirmed 检测
- current active session 排除
- planning contract 先给删除候选，再执行 cleanup

---

## 当前配置语义

Layer3 当前依赖 `OverallConfig.json.layer3_decay` 中的关键参数：

- `trimL2_interval`
- `shallow_interval`
- `deep_max_shallow`
- `Nretry_shallow`
- `Nretry_deep`

其中：

- `trimL2_interval` 控制 surface `L2` 的 trim 窗口
- `shallow_interval` 控制 surface 进入 shallow 的时间阈值
- `deep_max_shallow` 控制 shallow 进入 deep 的聚合门槛
- `Nretry_shallow / Nretry_deep` 控制各自 reduce 阶段的 retry 次数

---

## 角色边界

Layer3 聚焦于 preserve 之后的多层级衰减与长期结构整理。

围绕它的其他职责分布为：

- Layer1_Write：生成日级记忆
- Layer2_Preserve：提供 archive 与 restore 能力
- Layer4_Read：提供 recall / retrieval
- Installation / Adapters：承载安装、初始化与具体外部接入

---

## 与其他层的关系

### 向上游

Layer3 承接：

- Layer1 生成的 active surface memory
- Layer2 提供的 preserve 安全前提

### 向下游

Layer3 的输出会成为 Layer4 的长期读取来源之一：

- surface
- shallow
- deep

因此 Layer3 在整个产品中的位置是：

> 把已经写成的记忆继续压缩成更长时间尺度的表示，同时维持可读、可检索、可审计的长期结构。
