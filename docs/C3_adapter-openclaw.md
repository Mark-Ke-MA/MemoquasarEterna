# Adapter: OpenClaw

## 文档目标

本文档用于说明 **MemoquasarEterna** 中 OpenClaw adapter 的整体设计。

它回答的核心问题是：

- 为什么需要 `Adapters/openclaw/`
- OpenClaw adapter 在整个仓库架构中的位置是什么
- 它如何与 `Core/` 协作
- 当前内部按哪些能力域组织
- 哪些能力已经接入，哪些位置是演进接口位

这是一份**仓库级 adapter 文档**。

更具体的实现细节应分别进入：

- `Adapters/openclaw/README.md`
- `docs/C2_connector-contract.md`
- `docs/C1_architecture.md`

---

## 为什么需要 OpenClaw adapter

`Core/` 负责 memory engine 本体。

但 memory engine 要真正运行起来，还需要一个具体环境去提供：

- 原始会话输入
- 模型调用能力
- 运行时清理与 hook
- 平台侧插件包装
- session registry 生命周期管理

OpenClaw adapter 的存在，就是为了把这些平台能力整理成一套可被 core 稳定调用的接口。

一句话说：

> OpenClaw adapter 负责把 OpenClaw 平台上的输入、调用、插件与运行时机制，转换成 MemoquasarEterna core 可消费的能力集合。

---

## 在整体架构中的位置

在当前仓库中，OpenClaw adapter 位于：

```text
Adapters/openclaw/
```

它在整体架构中的位置可以表示为：

```text
Core/
  ↕
Adapters/openclaw/
  ↕
OpenClaw runtime / plugin / session environment
```

也就是说：

- `Core/` 不直接依赖 OpenClaw 的内部实现细节
- `Adapters/openclaw/` 负责把这些平台细节收口
- OpenClaw 平台自身提供 session、plugin、worker、registry 等运行环境

因此 OpenClaw adapter 是：

- 一个 bridge
- 一个 connector 化的能力收口层
- 当前最主要的 harness 接入实现

---

## OpenClaw adapter 与 `Core/` 的关系

当前 `Core/` 与 OpenClaw adapter 的协作依赖 connector contract。

核心规则是：

- `Core/` 只依赖固定能力名
- `Adapters/openclaw/CONNECTOR.py` 负责把内部实现暴露成固定键
- core 不直接关心 adapter 内部目录如何拆分

这让双方形成一种稳定边界：

### `Core/` 关心什么

`Core/` 关心：

- `call_llm`
- `prerequisites`
- `install`
- `uninstall`
- `extract`
- `harness_clean`
- `harness_preserve`
- `harness_decay`

### OpenClaw adapter 关心什么

OpenClaw adapter 关心：

- 这些能力在 OpenClaw 平台上具体如何实现
- session 从哪里读取
- worker 怎样启动
- plugin 怎样安装
- session watch 如何维护

这种关系让：

- core 更稳定
- adapter 更灵活
- 平台特化逻辑不会污染到 layer 主体

---

## `CONNECTOR.py` 的位置

OpenClaw adapter 的对外入口是：

```text
Adapters/openclaw/CONNECTOR.py
```

这是当前 OpenClaw adapter 的唯一对外收口点。

它的职责是：

- 把 adapter 内部的具体实现映射到固定 contract 键
- 向 core 暴露当前 harness 可用的能力

当前它暴露的映射包括：

- `call_llm`
- `prerequisites`
- `install`
- `uninstall`
- `extract`
- `harness_clean`
- `harness_preserve`
- `harness_decay`

因此，理解 OpenClaw adapter 的第一步，通常就是理解：

> 哪些平台能力被收口到了 `CONNECTOR.py`，以及它们在 adapter 内部分别指向哪里。

---

## 当前能力域拆分

OpenClaw adapter 当前按能力域组织，而不是按 Layer 平铺。

主要包括以下几个部分。

### 1. `Extract/`

这是 Layer0 对应的平台侧适配域。

它负责：

- 读取 OpenClaw sessions
- 读取 known-direct-sessions registry
- 汇总目标时间窗口内的相关 session
- 解析 `.jsonl` session 文件
- 归一化 turns 与文本
- 返回标准化输入给 Layer0

它解决的问题是：

> 如何把 OpenClaw 平台上的原始会话输入，转成 Layer0 可继续处理的标准输入。

### 2. `openclaw_call_LLM.py`

这是主 LLM 调用桥接。

它主要服务于：

- Layer1 Map / Reduce
- Layer3 reduce

它把 core 侧的 prompt / 任务调用转成 OpenClaw 平台上的 worker session 执行。

### 3. `openclaw_runtime_maintenance.py`

这是运行时维护桥接。

它当前主要用于：

- runtime 清理
- worker session 清理
- `harness_clean` hook

### 4. `Read/`

这是 OpenClaw read 插件适配域。

它承接：

- plugin `index.ts` 模板
- plugin manifest 模板
- 安装脚本

它把 `Core/Layer4_Read/` 的读取能力包装成 OpenClaw plugin tools。

它解决的问题是：

> 如何把 memory core 的读取能力，以 OpenClaw 原生插件工具的形式暴露给外部使用。

### 5. `Sessions_Watch/`

这是 OpenClaw active session registry 生命周期相关逻辑的业务域。

它当前承接：

- registry watch
- install / manage / runtime 机制
- preserve 接口位
- decay 接口位

其中：

- `Mechanisms/` 组织已有机制代码
- `Registries/` 存放 active registry
- `Preserve/` 承载 session watch preserve 接口位
- `Decay/` 承载 session watch decay 接口位

### 6. `Installation/`

这是 OpenClaw adapter 内部的安装与卸载入口域。

它当前通过 `CONNECTOR.py` 暴露为 `prerequisites`、`install` 与 `uninstall`。

随着 adapter 演进，它适合继续收口更多需要由 harness 自己负责的安装前预检、安装与卸载动作。

---

## OpenClaw adapter 支撑的 core 主链

从整体看，OpenClaw adapter 当前支撑了多条 core 主链。

### Layer0 主链

```text
OpenClaw sessions / registry
  ↓
Adapters/openclaw/Extract/
  ↓
Core/Layer0_Extract/
```

### Layer1 / Layer3 LLM 主链

```text
Core Layer1 / Layer3
  ↓
call_llm
  ↓
Adapters/openclaw/openclaw_call_LLM.py
  ↓
OpenClaw worker runtime
```

### Layer2 / Layer3 hook 主链

```text
Core Layer2 / Layer3
  ↓
harness_preserve / harness_decay / harness_clean
  ↓
Adapters/openclaw/...
```

### Layer4 read 主链

```text
Core/Layer4_Read/
  ↓
Adapters/openclaw/Read/
  ↓
OpenClaw plugin tools
```

因此，OpenClaw adapter 并不是单点桥接，而是同时承接：

- 输入接入
- 模型调用
- runtime hook
- plugin 包装
- session watch 生命周期管理

---

## `Read/` 与 Layer4 的关系

在当前架构中，读取能力本身属于：

```text
Core/Layer4_Read/
```

OpenClaw adapter 的 `Read/` 负责的是平台侧包装。

也就是说：

- Layer4 定义读取逻辑本身
- OpenClaw `Read/` 定义如何把这些入口包装成 OpenClaw plugin

当前实际链路是：

```text
OpenClaw plugin tool
→ index.ts
→ python3 Core/Layer4_Read/ENTRY_LAYER4_vague.py | ENTRY_LAYER4_exact.py
→ 返回 recall 结果
```

所以在整体架构里，`Read/` 的位置更接近：

- 平台侧暴露层
- 插件包装层
- Layer4 的 adapter 前端

---

## `Sessions_Watch/` 与 Layer2 / Layer3 的关系

`sessions watch` 的平台侧逻辑与 core 的 Layer2 / Layer3 形成对应关系。

### Preserve 方向

- Layer2 处理 memory surface 的 preserve / archive
- OpenClaw `Sessions_Watch/Preserve/` 处理 platform-side session registry / session files 的 preserve

### Decay 方向

- Layer3 处理 memory structure 的 decay
- OpenClaw `Sessions_Watch/Decay/` 处理 platform-side session watch data 的更谨慎整理

这意味着：

> OpenClaw adapter 不只是把 core 跑起来，还尝试让平台侧状态也拥有与 core 生命周期相对应的整理机制。

---

## 配置体系

OpenClaw adapter 当前主要依赖两层配置：

### `OverallConfig.json`

它提供：

- 当前使用哪个 harness
- agent 列表
- code/store 根路径
- timezone 与 window
- 产品名等仓库级信息

### `Adapters/openclaw/OpenclawConfig.json`

它提供：

- OpenClaw adapter 自己的路径模板
- sessions 路径
- registry 路径
- maintenance 路径
- archive 路径
- decay / preserve 相关平台配置

也就是说：

- `OverallConfig.json` 负责仓库级与产品级配置
- `OpenclawConfig.json` 负责 OpenClaw adapter 级配置

---

## 当前成熟度

从当前状态看，OpenClaw adapter 已经具备明确的主骨架，并已接上关键主链。

已经稳定落位的部分包括：

- `CONNECTOR.py`
- `Extract/`
- `call_llm`
- `runtime_maintenance`
- `Read/` 的模板与安装脚本
- `Sessions_Watch/` 的业务域结构

同时，也仍然保留了一些接口位，供后续继续演进。

这说明当前 OpenClaw adapter 的状态应理解为：

> 一套已经能够支撑 core 关键能力、并为后续平台侧生命周期逻辑留出稳定插座的 connector 化 adapter。

---

## 设计价值

OpenClaw adapter 当前最重要的价值有三点。

### 1. 平台差异被收口

core 不需要直接知道 OpenClaw 的目录、session、plugin 与运行机制细节。

### 2. 主链能力变得清晰

extract、call_llm、runtime hook、read plugin、sessions watch 各有稳定位置。

### 3. 后续扩展更容易定位

无论要扩展：

- preserve / decay
- plugin 能力
- install / uninstall 流程
- registry 生命周期

都已经有合适的能力域可继续演进。

---

## 推荐阅读顺序

如果你想理解 OpenClaw adapter，建议按以下顺序：

1. 先看 `docs/A1_installation-guide.md`
2. 再看 `docs/B1_maintenance-guide.md`
3. 再看 `docs/C1_architecture.md`
4. 然后看 `docs/C2_connector-contract.md`
5. 然后看 `Adapters/openclaw/README.md`
6. 再回到 `CONNECTOR.py`
7. 最后按能力域深入：
   - `Extract/`
   - `Read/`
   - `Sessions_Watch/`

---

## 一句话总结

当前 OpenClaw adapter 的核心定位是：

> **把 OpenClaw 平台上的会话输入、模型调用、runtime hooks、plugin 包装与 session watch 生命周期逻辑，整理成一套通过 `CONNECTOR.py` 暴露给 `Core/` 的稳定能力集合。**
