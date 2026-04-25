# Architecture

## 文档目标

本文档用于说明 **MemoquasarEterna** 当前代码仓库的整体架构。

它回答的核心问题是：

- 仓库为什么按现在的目录结构组织
- `Core/`、`Adapters/`、`Installation/`、`Maintenance/` 各自承担什么角色
- Layer0–4 与 LayerX 之间如何协作
- connector 与 adapter 在整体设计中的位置是什么
- 一次完整 memory pipeline 大致如何流动

这是一份**整体结构文档**。更细的实现细节应分别进入：

- `Core/README.md`
- 各 Layer 自己的 `README.md`
- `docs/C2_connector-contract.md`
- `docs/C3_adapter-openclaw.md`

---

## 总体结构

当前仓库根目录采用如下组织：

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

这套结构把整个产品分成四个层次：

- `Core/`
  - memory engine 本体
  - 承担写入、preserve、decay、read、landmark judge

- `Adapters/`
  - 外部环境接入层
  - 负责把 `Core/` 接到 OpenClaw 等具体 harness 上

- `Installation/`
  - 初始安装、初始 backfill、首次落地相关脚本

- `Maintenance/`
  - rerun、补跑、维护与人工运维脚本

一句话说：

> `Core/` 负责记忆系统本身，`Adapters/` 负责外部接入，`Installation/` 负责初始落地，`Maintenance/` 负责后续维护。

---

## 为什么这样分层

这套结构服务于三个目标：

### 1. 把 memory engine 与外部平台接入分开

记忆系统的核心逻辑，例如：

- 如何写入
- 如何 archive
- 如何 decay
- 如何 recall

应当保持为独立的 core。

外部平台差异，例如：

- OpenClaw session 如何读取
- 某个 harness 如何发起 `call_llm`
- 某个平台如何安装 plugin

则放到 adapter 中处理。

这样可以让：

- `Core/` 保持相对稳定
- `Adapters/` 负责环境特化
- 新增 harness 时尽量不改动 core 主体

### 2. 把“初始落地”与“后续维护”分开

初始 backfill、初始部署、首次初始化，与后续 rerun、补跑、日常维护，本质上是两类不同操作。

因此：

- `Installation/` 负责首次落地动作
- `Maintenance/` 负责后续人工维护动作

### 3. 让仓库结构更适合公开发布与长期维护

如果所有 Layer、脚本、adapter、安装逻辑全部平铺在根目录，结构会快速失控。

把目录职责明确化之后：

- 初次阅读更容易建立全局心智模型
- 文档入口更清晰
- 后续新增功能更容易找到合适位置

---

## `Core/` 的内部结构

当前 `Core/` 组织为：

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

其中：

### `shared_funcs.py`
负责 core 共用的最小公共函数，例如：

- 配置加载
- JSON 读写
- 标准输出辅助

### `harness_connector.py`
负责 connector 的加载与调用桥接。

它的职责是：

- 读取当前配置指定的 harness
- 加载 `Adapters/{harness}/CONNECTOR.py`
- 提供固定接口的必选/可选 callable 读取逻辑

### Layer0–4 与 LayerX
这六个目录构成 memory engine 的主体。

---

## Layer 体系

当前 memory core 使用 `Layer0 → Layer4 + LayerX` 的组织。

### Layer0_Extract
负责原始输入提取与标准化。

它把某个 agent 某一天的原始输入转换成 Layer0 产物，包括：

- surface `L2`
- surface `L1` 初始化文件
- staging 中间产物

### Layer1_Write
负责日级记忆写入主流水线。

它从 Layer0 开始，继续完成：

- chunk 规划
- Map/Reduce
- 正式写回
- L0 / embedding 更新
- statistics 记录
- 清理收尾

### Layer2_Preserve
负责 surface 层周级 preserve。

它提供：

- archive
- restore
- 周级归档日志

Layer2 为后续更长期的数据生命周期管理提供安全副本与可审计对象。

### Layer3_Decay
负责多层级 decay。

它在 preserve 已建立安全副本的前提下，对 active memory 做进一步整理，包括：

- trim L2
- shallow 聚合
- deep 聚合
- cleanup

### Layer4_Read
负责读取与召回。

它提供两条主线：

- vague recall
- exact recall

Layer4 把已经写成并经过整理的 memory 结构重新转换为可供 agent / harness 直接消费的读取结果。

### LayerX_LandmarkJudge
负责 landmark 判定。

它基于长期保留的 statistics records：

- 做结构化分析
- 打分
- 输出 landmark 判定

这个结果主要服务于 Layer3 的决策。

---

## Layer 之间的协作关系

### 写入主线

最核心的日级写入链路是：

```text
原始输入
  ↓
Layer0_Extract
  ↓
Layer1_Write
```

这条链把原始会话输入转换成 surface 层的正式记忆结构。

### preserve 与 decay 主线

在日级写入之后，系统继续进入更长期的数据整理过程：

```text
Layer1_Write
  ↓
Layer2_Preserve
  ↓
Layer3_Decay
```

其中：

- Layer2 负责先保住
- Layer3 负责继续减薄与整理

### read 主线

读取层基于已经写成并经过整理的结果工作：

```text
Layer1_Write / Layer2_Preserve / Layer3_Decay
  ↓
Layer4_Read
```

Layer4 读取的主要来源包括：

- surface
- shallow
- deep
- archived `L2`

### landmark judge 的位置

LayerX 主要与 Layer1 和 Layer3 相连：

```text
Layer1 Stage8 statistics
  ↓
LayerX_LandmarkJudge
  ↓
Layer3 decision making
```

因此 LayerX 更像一个跨层辅助判定层，而不是线性主流水线中的又一个写入层。

---

## 数据生命周期视角

如果从数据生命周期看，当前系统大致可以分成四段：

### 1. 输入接入
由 Layer0 完成。

目标是把原始输入变成统一可处理的结构。

### 2. 表层写入
由 Layer1 完成。

目标是把原始输入写成 surface 层可长期保留、可继续处理的正式记忆。

### 3. 长期整理
由 Layer2 + Layer3 完成。

目标是：

- 先建立安全副本
- 再逐层减薄
- 让长期记忆规模可控、结构可检索

### 4. 读取消费
由 Layer4 完成。

目标是把 memory core 中的结构化结果转换成上层 agent / harness 可直接消费的读取输出。

---

## connector 与 adapter 的关系

当前架构中，`Core/` 并不直接知道某个 harness 的内部实现细节。

它只知道一件事：

> 当前 harness 会在 `Adapters/{harness}/CONNECTOR.py` 中暴露一组固定接口。

### 为什么要有 `CONNECTOR.py`

因为 core 关心的是能力，而不是某个平台内部如何拆目录。

例如 core 只关心：

- memory worker 如何 `call_llm`
- memory worker 如何 `clean_runtime`
- production agent 如何 `extract`
- production agent 如何 `preserve`
- production agent 如何 `decay`

至于这些能力在 adapter 内部如何组织，交给 adapter 自己决定。

### 当前固定接口

当前 connector 约定包括：

- `memory_worker`：
  - `call_llm`
  - `clean_runtime`
  - `prerequisites`
  - `install`
  - `uninstall`

- `production_agent`：
  - `extract`
  - `preserve`
  - `decay`
  - `prerequisites`
  - `install`
  - `uninstall`

这样的好处是：

- `Core/` 只依赖稳定 contract
- `Adapters/` 可以独立演进内部结构
- 新 harness 接入时复用同一套能力边界

---

## OpenClaw 在整体架构中的位置

当前仓库中，OpenClaw 是最主要的 adapter 实现。

位置在：

```text
Adapters/openclaw/
```

它的职责包括：

- 提供 `CONNECTOR.py`
- 实现 Layer0 所需的 `extract`
- 实现 Layer1 / Layer3 所需的 `call_llm` 与 runtime hook
- 提供 Layer4 read 的平台侧包装模板
- 组织 Sessions_Watch 相关 preserve / decay 逻辑

也就是说，OpenClaw 并不是 memory engine 本体，而是当前 memory engine 的主要运行环境适配层。

---

## `Installation/` 与 `Maintenance/` 的位置

### `Installation/`
`Installation/` 主要承接：

- 初始 backfill
- 初始部署时的辅助脚本

它服务的是“第一次把系统落地起来”的场景。

### `Maintenance/`
`Maintenance/` 主要承接：

- rerun
- failed log 相关补跑
- 维护性操作

它服务的是“系统已经运行起来之后”的运维场景。

这两个目录让主仓库里的脚本角色更清楚：

- 首次落地看 `Installation/`
- 后续维护看 `Maintenance/`

---

## 当前架构的几个核心原则

### 1. core 与 adapter 分离
memory engine 与外部平台接入保持解耦。

### 2. connector contract 固定
core 通过稳定接口访问 adapter 能力。

### 3. layer 各司其职
写入、preserve、decay、read、judge 分别组织，不混在同一层中。

### 4. 读取层独立
读取能力由 Layer4 作为独立层承载，而不是嵌入到 connector contract 中。

### 5. 初始化与维护分离
首次落地与后续维护作为两类不同职责单独组织。

---

## 推荐阅读顺序

如果你第一次进入这个仓库，建议按以下顺序阅读：

1. 根目录 `README.md`
2. `docs/A1_installation-guide.md`
3. `docs/B1_maintenance-guide.md`
4. `Core/README.md`
5. 各 Layer README：
   - `Core/Layer0_Extract/README.md`
   - `Core/Layer1_Write/README.md`
   - `Core/Layer2_Preserve/README.md`
   - `Core/Layer3_Decay/README.md`
   - `Core/Layer4_Read/README.md`
   - `Core/LayerX_LandmarkJudge/README.md`
4. `Adapters/openclaw/README.md`
5. `docs/C2_connector-contract.md`
6. `docs/C3_adapter-openclaw.md`

---

## 一句话总结

MemoquasarEterna 当前采用的是一种：

> **以 `Core/` 为 memory engine、以 `Adapters/` 为外部接入层、以 `Installation/` 与 `Maintenance/` 组织运维脚本，并由 Layer0–4 + LayerX 分担完整记忆生命周期的分层架构。**
