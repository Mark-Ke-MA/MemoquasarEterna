# Layer0_Extract

## 这一层做什么

`Layer0_Extract/` 负责把某个 agent 某一天的原始对话输入整理成 **MemoquasarEterna** 的第一层标准产物。

它的职责是：

- 读取总配置
- 根据目标日期计算时间窗口
- 通过当前 harness 的 `extract` 接口获取标准化输入
- 组装并写出 surface `L2`、surface `L1` 初始化文件、以及 staging 中间产物
- 在需要时对已有结果执行 update 合并

Layer0 是整个系统里最靠近原始输入的一层，聚焦于标准化输入接入、窗口计算与 Layer0 产物组装。

---

## 输入

Layer0 的输入由三部分组成：

### 1. CLI 参数

主入口为：

- `ENTRY_LAYER0.py`

当前支持的核心参数：

- `--agent <agent_id>`
- `--date YYYY-MM-DD`
- `--write-l2`
- `--write-l1-init`
- `--write-staging`
- `--update`

当前还保留两类 harness 特有参数：

- `--session-alert`
- `--session-file <path>`

它们当前主要服务于 OpenClaw 场景，属于现阶段的 adapter 扩展参数。

### 2. 总配置

Layer0 读取 `OverallConfig.json` 中与以下内容相关的字段：

- `harness`
- `store_dir`
- `store_dir_structure`
- `timezone`
- `window`
- `empty_conversation_marker_suffix`

### 3. Harness connector

Layer0 通过当前 harness 的固定 connector 接口：

- `extract`

获取标准化输入。

---

## 输出

Layer0 会生成三类核心产物：

### 1. Surface L2

路径：

```text
{store_dir}/memory/{agentId}/surface/YYYY-MM/YYYY-MM-DD_l2.json
```

内容：

- 当天 conversation excerpts
- L2 status 信息

### 2. Surface L1 初始化文件

路径：

```text
{store_dir}/memory/{agentId}/surface/YYYY-MM/YYYY-MM-DD_l1.json
```

内容：

- 当天 L1 骨架
- status
- stats
- 后续 Layer1 / Layer3 会继续填充的核心字段占位

注意：

- Layer0 写入的是初始化态 L1
- 最终摘要内容会在后续写入流水线中继续完成

### 3. Staging 中间产物

路径：

```text
{store_dir}/staging/staging_surface/{agentId}/extraction_ready.json
```

内容：

- 供 Layer1 后续阶段使用的标准中间输入

在部分 harness 场景下，还可能额外写入：

```text
{store_dir}/staging/staging_surface/{agentId}/extraction_alert.json
```

这类文件属于特定 harness 场景下的扩展产物。

---

## 主入口

### `ENTRY_LAYER0.py`

这是 Layer0 的统一入口。

常见示例：

```bash
python3 ENTRY_LAYER0.py --agent <agent_id> --date <YYYY-MM-DD>
```

只写 L2：

```bash
python3 ENTRY_LAYER0.py --agent <agent_id> --date <YYYY-MM-DD> --write-l2
```

写 L1 初始化文件与 staging：

```bash
python3 ENTRY_LAYER0.py --agent <agent_id> --date <YYYY-MM-DD> --write-l1-init --write-staging
```

带 update 合并：

```bash
python3 ENTRY_LAYER0.py --agent <agent_id> --date <YYYY-MM-DD> --write-l2 --write-l1-init --write-staging --update
```

---

## 内部结构

`Layer0_Extract/` 当前主要由以下部分组成：

- `ENTRY_LAYER0.py`
  - 顶层 CLI 入口
  - 调度配置读取、窗口计算、connector 调用、写入控制

- `preprocess.py`
  - 加载配置
  - 计算 window
  - 生成 store 路径

- `postprocess.py`
  - 把标准化输入组装成 L1 / L2 / staging 写入包

也就是说，Layer0 当前是一个以：

- 轻 orchestration
- 轻 schema assembly
- 标准化输入接入

为主的入口层。

---

## 时间窗口

Layer0 按 `OverallConfig.json.window` 计算目标日期对应的时间范围。

当前默认语义是：

- day start: 当天 03:00
- day end: 次日 03:00
- boundary: 03:00

因此 `--date` 表示的是按 memory day 规则定义的目标日期，其时间范围由配置中的 boundary 决定。

---

## 写入策略

### 默认行为

当前默认参数组合是：

- `--write-l2`：开启
- `--write-l1-init`：关闭
- `--write-staging`：关闭
- `--update`：关闭

### `--update`

启用后，Layer0 会在写入前读取已有文件并执行合并，然后再回写目标文件。

它主要用于：

- 同一天多次提取
- 补写或续写已有 Layer0 结果

---

## 角色边界

Layer0 的边界集中在“标准化输入接入与初始化产物生成”。

围绕它的其他职责分布为：

- Adapter connector：提供具体 harness 的原始输入接入
- Layer1_Write：完成后续 chunk planning、Map/Reduce 与正式写回
- Layer2_Preserve：处理 surface 层 preserve / archive
- Layer3_Decay：处理多层级 decay
- Layer4_Read：处理读取与召回

---

## 与其他层的关系

### 向上游

Layer0 依赖当前 harness 提供的：

- `extract`

接口来拿到标准化输入。

### 向下游

Layer0 的输出主要被：

- `Layer1_Write`

消费。

其中：

- surface `L2`
- surface `L1` 初始化文件
- staging `extraction_ready.json`

构成了后续 Layer1 流水线的起点。
