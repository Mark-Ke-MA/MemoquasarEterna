# Connector Contract

本文档定义 `Core/` 与 `Adapters/` 之间的固定能力边界。具体 adapter 实现见 `docs/C3_adapter-openclaw.md`、`docs/C4_adapter-hermes.md`。

## 目标

connector contract 解决三件事：

- core 如何定位当前 harness 的 connector
- `Adapters/{harness}/CONNECTOR.py` 需要暴露哪些键
- 必选接口、可选 hook、调用参数与返回值如何约定

核心原则：`Core/` 只依赖能力名称，adapter 自己决定内部目录与实现细节。

## 文件位置与加载

```text
Adapters/{harness}/CONNECTOR.py
```

core 通过 `Core/harness_connector.py`：

- 读取 `memory_worker_harness` 与 `production_agents[*].harness`
- 加载对应 `CONNECTOR.py`
- 为 PA 组装 agent-wise / harness-wise routing
- 获取 required / optional callable 并调用

`CONNECTOR.py` 应暴露 dict。core 按顺序尝试：

1. `{HARNESS_NAME_UPPER}_CONNECTOR`
2. `CONNECTOR`

推荐直接使用：

```python
CONNECTOR = {...}
```

## 固定结构

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

## 顶层接口

| 接口 | 必选 | 语义 |
| --- | --- | --- |
| `ensure_config` | yes | 检查 / 生成当前 adapter 的本地 config，并校验 `schema_version` |

`ensure_config` 属于 harness adapter 顶层，不属于 MW 或 PA。

## memory_worker 接口

| 接口 | 类型 | 主要消费者 | 语义 |
| --- | --- | --- | --- |
| `call_llm` | 必选 | Layer1 Map/Reduce、Layer3 reduce | 把 core prompt / 任务交给当前 harness 的模型调用能力 |
| `clean_runtime` | 可选 hook | Layer1 Stage1、Layer3 Phase0 | 清理 MW runtime / worker sessions 等任务型状态 |
| `prerequisites` | 必选 | `Installation/INSTALL.py` | MW 侧安装前预检 |
| `install` | 必选 | `Installation/INSTALL.py` | MW 侧安装动作 |
| `uninstall` | 必选 | `Installation/UNINSTALL.py` | MW 侧卸载动作 |

MW 是专用内部 worker，不应与 PA 混用。

## production_agent 接口

| 接口 | 类型 | 主要消费者 | 语义 |
| --- | --- | --- | --- |
| `extract` | 必选 | Layer0 | 从 harness 原始输入源读取并归一化为 Layer0 标准输入 |
| `preserve` | 可选 hook | Layer2 | PA 侧平台状态 preserve，例如 session registry archive |
| `decay` | 可选 hook | Layer3 | PA 侧平台状态 decay，例如 session watch 清理 |
| `prerequisites` | 必选 | `Installation/INSTALL.py` | PA 侧安装前预检，按 harness 分组传入 `agent_ids` |
| `install` | 必选 | `Installation/INSTALL.py` | PA 侧安装动作，按 harness 分组传入 `agent_ids` |
| `uninstall` | 必选 | `Installation/UNINSTALL.py` | PA 侧卸载动作，按 harness 分组传入 `agent_ids` |

## 调用规则

| 读取方式 | 行为 |
| --- | --- |
| `get_required_connector_callable(...)` | connector、role、key 缺失或不可调用时直接报错 |
| `get_optional_connector_callable(...)` | 缺失时返回 `None`；存在但不可调用时报错 |
| `call_optional_connector(...)` | optional callable 存在才调用 |

required 接口构成主链；optional hook 用于 platform-specific 扩展。

## Hook 参数

当前可选 hook 统一接收：

```python
def some_hook(context: dict) -> Any:
    ...
```

最小公共结构：

```python
{
  "repo_root": <repo_root>,
  "inputs": {...}
}
```

对于按 harness 分组调用的 PA hook，core 会在 `context["inputs"]["agent_ids"]` 中放入当前 harness 负责的 agent 列表。

## 返回值

返回值保持宽松：

- adapter 可返回自己的结构
- core 只读取当前调用点真正需要的字段
- 需要稳定 schema 的位置，应由对应 Layer 或 adapter 文档单独说明

安装类接口建议返回：

```python
{
  "success": True,
  "status": "...",
  "dry_run": False,
  "steps": [...],
  "warnings": [...]
}
```

## 当前实现矩阵

| 接口 | OpenClaw | Hermes |
| --- | --- | --- |
| `ensure_config` | yes | yes |
| `memory_worker.call_llm` | yes | no |
| `memory_worker.clean_runtime` | yes | no |
| `memory_worker.prerequisites` | yes | no |
| `memory_worker.install` | yes | no |
| `memory_worker.uninstall` | yes | no |
| `production_agent.extract` | yes | yes |
| `production_agent.preserve` | yes | no |
| `production_agent.decay` | yes | no |
| `production_agent.prerequisites` | yes | yes |
| `production_agent.install` | yes | yes |
| `production_agent.uninstall` | yes | yes |

说明：

- OpenClaw 是当前 production/default adapter，完整接入 MW 与 PA 主链。
- Hermes 是 experimental PA adapter，只支持 Layer0 extract 与 Layer4 recall skill install lifecycle。
- 不应把 `memory_worker_harness` 设置为 `hermes`。

## Layer4 的位置

Layer4 read 不属于 connector 固定键。读取逻辑由 `Core/Layer4_Read/` 提供，adapter 只负责把它包装成平台可消费形式：

| Adapter | Layer4 包装 |
| --- | --- |
| OpenClaw | plugin tools + skill 引导 |
| Hermes | profile-local `memoquasar-memory-recall` skill |

## 演进原则

- 只有跨 harness 公共能力才考虑进入 fixed contract。
- 优先新增 optional hook，而不是立刻新增 required 接口。
- adapter 内部可以拆分，但 `CONNECTOR.py` 必须继续作为唯一对外入口。
- 修改 contract 时同步更新本文档、对应 adapter 文档和 `Core/harness_connector.py`。

## 一句话总结

connector contract 让 `Core/` 只依赖稳定能力边界，让 `Adapters/` 自由组织内部实现，并通过 `CONNECTOR.py` 统一收口。
