# Adapters/openclaw

## 定位

`Adapters/openclaw/` 是 **MemoquasarEterna** 当前用于对接 **OpenClaw harness** 的 adapter。

它的作用是把 memory core 所需的能力，组织成可被 `Core/` 稳定调用的 OpenClaw 接入层。

这里承载的是：

- connector 收口
- Layer0 extract 的平台侧适配
- Layer1 / Layer3 所需的 LLM 与 runtime 相关桥接
- OpenClaw read plugin 的模板与安装脚本
- sessions watch 的业务域

一句话说：

> `Core/` 负责 memory engine，本目录负责把这个 engine 接到 OpenClaw 上。

---

## 在仓库中的位置

`Adapters/openclaw/` 是当前最主要的 harness adapter 实现。

它与其他目录的关系是：

- `Core/`
  - 通过 `CONNECTOR.py` 调用 OpenClaw 侧能力

- `Installation/`
  - 负责仓库级的初始 backfill 与安装脚本组织

- `Maintenance/`
  - 负责 rerun、补跑与维护脚本

因此本目录在整个仓库中的角色是：

- 承接 OpenClaw 平台差异
- 实现 connector contract
- 把平台能力转换成 core 可消费的固定接口

---

## 当前结构

```text
Adapters/openclaw/
  OpenclawConfig-template.json
  CONNECTOR.py
  openclaw_shared_funcs.py

  openclaw_call_LLM.py
  openclaw_runtime_maintenance.py

  Extract/
  Installation/
  Read/
  Sessions_Watch/
```

---

## 设计主线

### 1. `CONNECTOR.py` 是唯一对外入口

`Core/` 不直接依赖 OpenClaw adapter 的内部目录结构。

`Core/` 只需要：

- 加载 `Adapters/openclaw/CONNECTOR.py`
- 读取固定 connector 键
- 调用对应 callable

这样可以让 adapter 内部继续演进，而不把平台细节暴露给 core。

### 2. 必选接口与可选 hooks 分开

当前 connector 约定分成：

#### 必选接口
- `memory_worker.call_llm`
- `memory_worker.prerequisites`
- `memory_worker.install`
- `memory_worker.uninstall`
- `production_agent.extract`
- `production_agent.prerequisites`
- `production_agent.install`
- `production_agent.uninstall`

#### 可选接口
- `memory_worker.clean_runtime`
- `production_agent.preserve`
- `production_agent.decay`

这种结构让：

- 主链能力保持固定
- 平台扩展能力可以逐步补齐

### 3. hook 统一接收 `context`

当前可选 hook 统一接收：

```python
def some_hook(context: dict) -> Any:
    ...
```

`context` 当前主要包含：

- `repo_root`
- `inputs`

这样更适合 adapter 侧自由演进内部参数结构。

---

## 当前 connector contract 映射

当前 `CONNECTOR.py` 暴露：

- `memory_worker.call_llm`
  - 指向 `openclaw_call_LLM.openclaw_call_subagent_readandwrite`

- `memory_worker.prerequisites`
  - 指向 `Installation/MEMORY_WORKER_PREREQUISITES.py`

- `memory_worker.install`
  - 指向 `Installation/MEMORY_WORKER_INSTALL.py`

- `memory_worker.uninstall`
  - 指向 `Installation/MEMORY_WORKER_UNINSTALL.py`

- `production_agent.extract`
  - 指向 `Extract/core.py` 中的 `fetch_openclaw_layer0_input`

- `production_agent.prerequisites`
  - 指向 `Installation/PRODUCTION_AGENT_PREREQUISITES.py`

- `production_agent.install`
  - 指向 `Installation/PRODUCTION_AGENT_INSTALL.py`

- `production_agent.uninstall`
  - 指向 `Installation/PRODUCTION_AGENT_UNINSTALL.py`

- `memory_worker.clean_runtime`
  - 指向 `openclaw_runtime_maintenance.openclaw_harness_maintenance_hook`

- `production_agent.preserve`
  - 指向 `Sessions_Watch/Preserve/entry.py`

- `production_agent.decay`
  - 指向 `Sessions_Watch/Decay/entry.py`

---

## 目录职责

### `openclaw_call_LLM.py`

负责 OpenClaw harness 下的主 LLM 调用桥接。

当前主要服务于：

- Layer1 Stage3 / Stage4
- Layer3 reduce 阶段

它的主要工作包括：

- 接收 prompt 或任务请求
- 启动 memory worker session
- 等待运行结束
- 返回结果给 core

### `openclaw_runtime_maintenance.py`

负责 runtime 相关的维护与清理。

当前主要承接：

- memory worker sessions 清理
- `memory_worker.clean_runtime` hook

### `Extract/`

这是 OpenClaw adapter 的 Layer0 extract 适配域。

它负责：

- 读取 OpenClaw session 数据
- 读取 known-direct-sessions registry
- 汇总目标日期 / 时间窗口内应纳入的 session
- 解析 `.jsonl` session 文件
- 清洗 turns 与文本
- 返回给 Layer0 的标准化输入

主要文件包括：

- `core.py`
- `session_parser.py`
- `message_normalize.py`

### `Installation/`

这是 OpenClaw adapter 内部的安装与卸载入口域。

当前主要承接：

- `MEMORY_WORKER_PREREQUISITES.py`
- `MEMORY_WORKER_INSTALL.py`
- `MEMORY_WORKER_UNINSTALL.py`
- `PRODUCTION_AGENT_PREREQUISITES.py`
- `PRODUCTION_AGENT_INSTALL.py`
- `PRODUCTION_AGENT_UNINSTALL.py`
- memory worker workspace 模板与安装
- openclaw.json merge example 的渲染

后续适合继续收口更多需要由 harness 自己负责的安装/卸载动作。

### `Read/`

这是 OpenClaw read 适配域。

注意：当前 `Read/` 的定位是 **工具插件 + skill 引导**，而不是 OpenClaw 的 memory backend；当前版本不应通过 `plugins.slots.memory` 将 MemoquasarEterna 设为 active memory plugin。

它当前承载：

- `index.ts.template`
- `openclaw.plugin.json.template`
- `installation.sh`
- `skills/`

这部分的职责是把 `Core/Layer4_Read/` 的读取能力包装成 OpenClaw plugin tools，并随插件一起安装引导 agent 使用 recall 的 skill。

当前安装脚本会：

- 创建 extension 目录
- 渲染模板并写出 `index.ts` 与 `openclaw.plugin.json`
- 复制 `skills/` 目录到真实插件目录
- 从 `OverallConfig.json` 中读取产品名与 agent 列表
- 把当前 repo 的绝对路径写入生成后的 plugin 入口

### `Sessions_Watch/`

这是 OpenClaw session registry 生命周期相关逻辑的业务域。

当前包含：

- `Mechanisms/`
  - 既有 sessions watch 机制代码
  - 包括 install、manage、runtime 相关逻辑

- `Registries/`
  - `{agentId}/known-direct-sessions.json`
  - 每个 agent 的 active registry

- `Preserve/`
  - session watch preserve 接口位
  - 当前挂在 `production_agent.preserve`

- `Decay/`
  - session watch decay 接口位
  - 当前挂在 `production_agent.decay`

在业务上，`Sessions_Watch/` 承接的是：

- active direct-session registry 的维护
- watch plist / daily cron 相关机制
- session registry 的 preserve / decay 演进位

---

## `Extract/` 的角色

`Extract/` 主要服务于 Layer0。

它从 OpenClaw 的：

- sessions
- known-direct-sessions registry

中读取输入，并整理成标准化 turns。

也就是说，`Extract/` 解决的是：

> 如何把 OpenClaw 平台上的原始会话输入，转成 Layer0 可以继续处理的标准输入。

---

## `Read/` 的角色

`Read/` 主要服务于 Layer4。

它把 `Core/Layer4_Read/` 的读取入口包装成 OpenClaw plugin tools，并通过 plugin-shipped skill 引导 agent 在回忆类请求下优先使用这些 recall 工具。

当前已形成的主链路是：

```text
OpenClaw plugin tool
→ index.ts
→ python3 Core/Layer4_Read/ENTRY_LAYER4_vague.py | ENTRY_LAYER4_exact.py
→ 返回 recall 结果
```

同时，插件会随 `openclaw.plugin.json` 一起声明并安装 `skills/` 目录，使新 session 能自动加载对应 skill。

因此，`Read/` 解决的是：

> 如何把 memory core 的读取能力，以 OpenClaw 原生插件工具的形式暴露出来，并让 agent 更自然地在合适场景下调用这些工具。

---

## `Sessions_Watch/` 的角色

`sessions watch` 在当前 adapter 中是一个独立业务域，而不是零散脚本集合。

它当前承接两类事情：

### 1. 已经存在的 watch 机制

包括：

- 维护 `known-direct-sessions.json`
- 管理 watch plist
- 触发 runtime 更新
- 管理 daily cron

### 2. 后续 session registry 生命周期整理

包括：

- preserve
- decay
- archive-confirmed 后的更长期整理

因此 `Sessions_Watch/` 的整体定位是：

> OpenClaw active session registry 生命周期相关逻辑的总域。

### Preserve

`Sessions_Watch/Preserve/` 当前承载的是 session watch preserve 接口位。

它围绕的核心流程是：

- 读取 active registry
- 接收来自 core 的 week context
- 用 week 推导 preserve sweep boundary
- 汇总符合时间条件的 session UUID
- 排除 current direct session
- 复制对应 session files 到 harness archive
- 合并并写出 archived registry

其核心目标是：

> 为 session registry 建立可累积、可审计的 harness archive。

### Decay

`Sessions_Watch/Decay/` 当前承载的是 session watch decay 接口位。

它围绕的核心流程是：

- 读取 active registry
- 基于 target week 与 decay interval 计算 boundary
- 先做 archive-confirmed 检查
- 再构建 active registry 与 session files 的删除候选
- 依据配置执行 registry decay 与更谨慎的 file decay

其核心目标是：

> 在 preserve 已确认写入 archive 的前提下，对 active session watch 数据做更保守的整理与减薄。

---

## 配置依赖

### `OverallConfig.json`

当前主要提供：

- `harness`
- `agentId_list`
- `memory_worker_agentId`
- `code_dir`
- `store_dir`
- `timezone`
- `window`
- `product_name`

### `OpenclawConfig.json`

当前主要提供：

- `adapter_dirname`
- `sessions_path`
- `sessions_registry_path`
- `maintenance.launch_agents_dir`
- `maintenance.log_base_dir`
- `maintenance.plist_label_prefix`
- `sessions_registry_maintenance.*`
- `sessions_registry_archive_path`
- `sessions_files_archive_dir`

其中 `adapter_dirname` 用于让 adapter 内部路径组织保持可配置，而不是写死目录名。

仓库跟踪的默认模板是 `OpenclawConfig-template.json`。本地实际运行读取 `OpenclawConfig.json`；如果它不存在，顶层 `Installation/INSTALL.py` 会从模板生成一份。请只修改本地 `OpenclawConfig.json`，不要提交本机私有配置。

---

## 当前状态

截至当前版本，OpenClaw adapter 已经形成以下稳定主链：

- Layer0 extract
- Layer1 主链所需的 `call_llm` 与 runtime maintenance
- Layer2 archive 对应的 harness preserve 接口位
- Layer3 对应的 harness decay 接口位
- Layer4 read 的 plugin 模板与安装脚本

也就是说，当前 `Adapters/openclaw/` 已经不是目录草稿，而是一套：

> 可被 `Core/` 加载、调用并继续扩展的 connector 化 adapter 骨架。

---

## 阅读顺序建议

如果你第一次进入 OpenClaw adapter，建议按以下顺序阅读：

1. 先看 `Adapters/openclaw/README.md`
2. 再看 `CONNECTOR.py`
3. 然后按能力域进入：
   - `Extract/`
   - `Read/`
   - `Sessions_Watch/`
4. 需要总体规则时再看：
   - `docs/C2_connector-contract.md`
   - `docs/C3_adapter-openclaw.md`

---

## 一句话总结

`Adapters/openclaw/` 是当前 MemoquasarEterna 的 OpenClaw adapter：

> 它通过 `CONNECTOR.py` 把 OpenClaw 平台上的输入提取、LLM 调用、runtime hooks、read plugin 包装与 session watch 生命周期逻辑收口成一套可被 `Core/` 稳定调用的固定能力集合。
