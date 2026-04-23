# Core

## 定位

`Core/` 是 **MemoquasarEterna** 的 **memory core**。

这里存放的是产品的核心实现：

- 记忆写入
- surface preserve
- 多层级 decay
- recall / read
- landmark judge
- 以及这些层共用的最小运行基础设施

一句话说：

> `Core/` 负责记忆系统本身；`Adapters/` 负责把它接到具体外部环境上。

---

## 仓库中的位置

`Core/` 在整个仓库中负责 memory engine 本体。

与之配套的其他目录分别承担：

- `Adapters/`：外部平台适配与模板封装
- `Installation/`：初始安装与初始 backfill 脚本
- `Maintenance/`：rerun、补跑与维护脚本

---

## 目录结构

当前 `Core/` 包含：

- `shared_funcs.py`
  - core 全局共享的最小公共函数
  - 包括配置加载、JSON 读写、输出辅助等

- `harness_connector.py`
  - connector 加载与固定接口调用辅助
  - 负责把 `Core/` 与 `Adapters/{harness}/CONNECTOR.py` 接起来

- `Layer0_Extract/`
  - 原始输入提取与标准化入口层

- `Layer1_Write/`
  - 日级记忆写入主流水线

- `Layer2_Preserve/`
  - surface 层周级 preserve / archive / restore

- `Layer3_Decay/`
  - 多阶段、多层级记忆衰减

- `Layer4_Read/`
  - vague recall 与 exact recall 读取层

- `LayerX_LandmarkJudge/`
  - landmark 统计分析与判定辅助层

---

## 各层一句话职责

### Layer0_Extract
把某个 agent 某一天的原始输入整理成标准 Layer0 产物。

### Layer1_Write
从 Layer0 开始，完成 chunk 规划、Map/Reduce、正式写回、索引更新与清理收尾。

### Layer2_Preserve
在 surface 层上按周建立安全副本，并提供 archive / restore 能力。

### Layer3_Decay
在 preserve 已建立安全副本的前提下，对 active memory 做分层减薄。

### Layer4_Read
把已经写成并经过整理的 memory 结构重新转成可供 agent / harness 直接消费的召回结果。

### LayerX_LandmarkJudge
基于长期保留的 statistics records，对单日记忆做 landmark 判定，供 Layer3 决策使用。

---

## `Core/` 与其他目录的关系

### `Adapters/`
`Adapters/` 负责外部平台适配。

它的职责是：

- 实现固定 connector contract
- 包装 OpenClaw 等具体 harness 的能力
- 把 `Core/` 的入口暴露给外部运行环境

### `Installation/`
`Installation/` 负责初始安装 / 初始回填相关脚本。

### `Maintenance/`
`Maintenance/` 负责 rerun、补跑、维护操作等管理脚本。

因此整个仓库的关系可以概括为：

- `Core/`：记忆系统核心实现
- `Adapters/`：外部环境接入层
- `Installation/`：初始化与初始回填
- `Maintenance/`：后续维护与补跑

---

## 阅读顺序建议

如果你第一次阅读这个仓库，建议按以下顺序：

1. 先看根目录 `README.md`
2. 再看 `Core/README.md`
3. 然后按需要进入各层：
   - `Layer0_Extract/README.md`
   - `Layer1_Write/README.md`
   - `Layer2_Preserve/README.md`
   - `Layer3_Decay/README.md`
   - `Layer4_Read/README.md`
   - `LayerX_LandmarkJudge/README.md`
4. 总体架构说明见后续 `docs/architecture.md`
5. connector 边界说明见后续 `docs/connector-contract.md`

---

## 设计原则

`Core/` 当前遵循这些原则：

- 核心逻辑与 adapter 包装分离
- connector contract 固定，外部平台按 contract 适配
- 各 layer 各司其职，不把边界混在一起
- 读取能力由 `Layer4_Read/` 作为 core 读取层独立提供

因此，`Core/` 在整个产品中的定位是：

> 一个可被不同 harness / adapter 调用的、相对独立的 memory engine。
