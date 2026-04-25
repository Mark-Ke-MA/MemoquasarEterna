# Connector Contract

## 文档目标

本文档定义 **MemoquasarEterna** 中 `Core/` 与 `Adapters/` 之间的固定 connector contract。

它回答的核心问题是：

- `Core/` 如何定位当前 harness 的 connector
- `Adapters/{harness}/CONNECTOR.py` 需要暴露哪些键
- 哪些接口是必选，哪些接口是可选
- hook 的调用参数如何组织
- core 在调用 connector 时遵循什么原则

这份文档的目标不是描述某个具体 adapter 的内部实现，而是定义：

> **core 与 adapter 之间稳定、可复用、可演进的能力边界。**

---

## 为什么需要 connector contract

`Core/` 负责 memory engine 本体。

`Adapters/` 负责把这个 engine 接到具体运行环境，例如 OpenClaw。

如果 core 直接依赖某个 adapter 的内部目录结构，那么：

- adapter 内部一旦重构，core 就要跟着改
- 新增 harness 时很难复用现有接入方式
- core 会被具体平台实现细节污染

因此当前架构采用固定 contract：

- core 只依赖能力名称
- adapter 自己决定内部怎么拆目录、怎么组织脚本
- `CONNECTOR.py` 作为唯一对外入口，把内部实现收口成固定键集合

---

## 目录位置

当前 contract 的承载文件位置是：

```text
Adapters/{harness}/CONNECTOR.py
```

例如：

```text
Adapters/openclaw/CONNECTOR.py
```

core 通过 `Core/harness_connector.py` 来：

- 读取当前配置指定的 harness
- 加载对应 `CONNECTOR.py`
- 获取必选或可选 callable
- 统一执行调用

---

## connector 的暴露形式

`CONNECTOR.py` 当前应暴露一个 `dict`。

core 会按以下候选名称读取：

1. `{HARNESS_NAME_UPPER}_CONNECTOR`
2. `CONNECTOR`

例如对于 `openclaw`，会优先尝试：

- `OPENCLAW_CONNECTOR`
- `CONNECTOR`

当前推荐直接暴露：

```python
CONNECTOR = {
    ...
}
```

---

## 当前固定键集合

当前 contract 包含一个 harness 顶层配置入口，并按 agent role 分为两个能力子空间：

```python
CONNECTOR = {
    'ensure_config': ...,
    'memory_worker': {
        'call_llm': ...,
        'clean_runtime': ...,
        'prerequisites': ...,
        'install': ...,
        'uninstall': ...,
    },
    'production_agent': {
        'extract': ...,
        'preserve': ...,
        'decay': ...,
        'prerequisites': ...,
        'install': ...,
        'uninstall': ...,
    },
}
```

### `ensure_config`

面向当前 harness adapter 的本地配置引导。

固定语义是：

- 检查 adapter 本地 `Config.json` 是否存在
- 不存在时从 adapter 自己的 `Config-template.json` 生成
- 校验本地 config 的 `schema_version` 与当前 template 一致

这个接口属于 harness adapter 顶层，不属于 `memory_worker` 或 `production_agent`。

### `memory_worker`

面向专用 memory worker agent。

固定接口包括：

- `call_llm`
- `clean_runtime`
- `prerequisites`
- `install`
- `uninstall`

### `production_agent`

面向被记忆系统服务的生产级 agent。

固定接口包括：

- `extract`
- `preserve`
- `decay`
- `prerequisites`
- `install`
- `uninstall`

---

## `memory_worker` 接口

### `memory_worker.call_llm`

这是 core 侧需要的主 LLM 调用入口。

它主要被：

- Layer1 的 Map / Reduce 阶段
- Layer3 的 reduce 阶段

消费。

这个接口负责把 core 提供的 prompt 或任务请求，转交给当前 harness 能够提供的模型调用能力。

由于不同 harness 的运行环境差异很大，`call_llm` 的内部实现由 adapter 自己决定。

### `memory_worker.clean_runtime`

这是运行前或阶段切换前的 memory worker runtime 清理 hook。

它适用于：

- runtime 目录清理
- worker session 清理
- 其他 adapter 侧的预清理动作

### `memory_worker.prerequisites`

这是当前 harness 的安装前预检入口。

它承接的是当前 adapter 认为应由 harness 自己负责的 prerequisites 检查与必要的交互补全。

在不同 harness 中，这可能包括：

- harness-specific config 合法性检查
- 平台根路径 / 安装位置检查
- 平台专属字段的交互补全
- 其他平台相关前置条件检查

### `memory_worker.install`

这是当前 harness 的安装入口。

它承接的是当前 adapter 认为应由 harness 自己负责的安装动作。

在不同 harness 中，这可能包括：

- 初始脚本安装
- 平台侧插件注册
- worker workspace 建设
- 其他平台相关安装动作

### `memory_worker.uninstall`

这是当前 harness 的卸载入口。

它承接的是当前 adapter 认为应由 harness 自己负责的卸载动作。

在不同 harness 中，这可能包括：

- 插件目录清理
- worker workspace 删除
- 系统级 watcher / launchd / cron 的清理
- 其他平台相关卸载动作

---

## `production_agent` 接口

### `production_agent.extract`

这是 Layer0 所需的标准化输入提取入口。

它的职责是：

- 从当前 harness 的原始输入源中读取数据
- 完成 adapter 侧清洗与归一化
- 返回可供 Layer0 继续处理的标准输入结构

### `production_agent.preserve`

这是 preserve 相关的 harness hook。

它适用于：

- session registry 归档
- 平台侧 preserve
- 与 Layer2 对应的外部状态整理

### `production_agent.decay`

这是 decay 相关的 harness hook。

它适用于：

- session watch 的减薄或清理
- 平台侧 decay
- 与 Layer3 对应的外部状态整理

### `production_agent.prerequisites`

这是生产 agent 侧安装前预检入口。

### `production_agent.install`

这是生产 agent 侧安装入口。

### `production_agent.uninstall`

这是生产 agent 侧卸载入口。

---

## 调用约定

### 必选接口的读取

core 会通过 `get_required_connector_callable(...)` 读取必选接口。

这意味着：

- 若 connector 不存在，则报错
- 若对应 role 或键不存在，则报错
- 若对应值不可调用，则报错

因此，必选接口是 contract 的稳定主干。

### 可选接口的读取

core 会通过 `get_optional_connector_callable(...)` 或 `call_optional_connector(...)` 读取可选接口。

这意味着：

- 若 connector 不存在，可选接口返回 `None`
- 若键不存在，返回 `None`
- 若值存在但不可调用，则报错

因此，可选接口用于扩展 adapter 能力，而不阻塞 core 主流水线。

---

## hook 的参数组织

当前所有可选 hook 统一接收：

```python
def some_hook(context: dict) -> Any:
    ...
```

当前 `context` 采用最小公共结构：

```python
{
  "repo_root": <repo_root>,
  "inputs": {...}
}
```

其中：

- `repo_root`
  - 当前仓库根目录
- `inputs`
  - 当前阶段透传给 hook 的业务输入

### 为什么统一成 `context`

这样设计有几个好处：

- core 不需要知道每个 hook 具体要多少散参数
- adapter 可以自由扩展 `inputs` 的内部字段
- 后续增加 hook 时，更容易保持接口形状稳定

也就是说，core 只承诺：

- 调用时会给你一个 `context`
- 其中有 `repo_root`
- 其中有 `inputs`

至于 `inputs` 中每个字段如何解释，由对应 hook 自己定义并消费。

---

## 返回值约定

当前 contract 对返回值保持宽松策略。

也就是说：

- 必选接口可以返回 adapter 自己定义的结构
- 可选 hook 也可以返回 adapter 自己定义的结构
- core 只在特定调用点消费它真正需要的字段

这种设计的原则是：

- contract 先固定“入口能力”
- 返回结构在 adapter 演进过程中保留一定灵活性

对于需要稳定输出 schema 的位置，应由对应 layer 或对应 adapter 文档单独说明。

---

## core 的使用原则

当前 core 在使用 connector contract 时遵循以下原则：

### 1. core 只关心能力，不关心内部目录结构

core 只知道：

- 要去加载 `CONNECTOR.py`
- 要去读取固定键
- 要去调用返回的 callable

core 不关心：

- adapter 内部目录如何拆
- 哪个函数藏在哪个子目录里
- 哪个脚本是从旧版迁移过来的

### 2. 必选接口保持收敛

当前 contract 故意把必选接口压到最少，只保留真正构成主链的能力。

这样可以让：

- 新 harness 更容易接入
- core 不至于对 adapter 提太多强耦合要求

### 3. 扩展能力走可选 hook

当某些能力只适用于部分 harness 时，优先放进：

- `memory_worker.clean_runtime`
- `production_agent.preserve`
- `production_agent.decay`

或后续新增的可选 hook，而不是把所有能力都塞进必选接口。

### 4. Layer4 read 作为独立读取层存在

当前读取能力由 `Core/Layer4_Read/` 独立承载。

因此，connector contract 当前并不把 `read` 作为固定键的一部分。

Layer4 的平台侧包装应由相应 adapter 自己组织，并在 adapter 文档中说明。

---

## OpenClaw 当前实现示例

以 `Adapters/openclaw/CONNECTOR.py` 为例，当前暴露：

```python
CONNECTOR = {
    'memory_worker': {
        'call_llm': ...,
        'clean_runtime': ...,
        'prerequisites': ...,
        'install': ...,
        'uninstall': ...,
    },
    'production_agent': {
        'extract': ...,
        'preserve': ...,
        'decay': ...,
        'prerequisites': ...,
        'install': ...,
        'uninstall': ...,
    },
}
```

这说明当前 OpenClaw adapter 已经接入了完整的固定键集合。

其中：

- `memory_worker.call_llm` 对接 OpenClaw 的模型调用能力
- `memory_worker.clean_runtime` 对接 memory worker runtime 清理逻辑
- `production_agent.extract` 对接 Layer0 的输入提取能力
- `production_agent.preserve`、`production_agent.decay` 对接平台侧 session watch 逻辑

---

## 演进原则

后续如果要扩展 connector contract，建议遵循以下顺序：

### 1. 先判断是否真的是跨 harness 公共能力

只有当某项能力在多个 harness 中都稳定存在时，才考虑进入固定 contract。

### 2. 优先增加可选 hook，而不是立刻增加必选接口

这样可以降低对现有 adapter 的破坏面。

### 3. 保持 `CONNECTOR.py` 作为唯一对外入口

即使 adapter 内部继续拆分，也应当由 `CONNECTOR.py` 统一收口。

### 4. 在新增 contract 字段时同步更新文档

包括：

- 本文档
- 对应 adapter 文档
- 必要时更新 `Core/harness_connector.py`

---

## 一句话总结

当前 connector contract 的核心思想是：

> **让 `Core/` 只依赖稳定的能力边界，让 `Adapters/` 自由组织内部实现，并通过 `CONNECTOR.py` 把这些能力收口成统一接口。**
