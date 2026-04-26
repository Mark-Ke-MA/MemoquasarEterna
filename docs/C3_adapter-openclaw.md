# Adapter: OpenClaw

本文档说明 `Adapters/openclaw/` 的职责、能力域和当前成熟度。connector 固定接口见 `docs/C2_connector-contract.md`。

## 定位

`Core/` 负责 memory engine，本身不直接理解 OpenClaw session、plugin、worker runtime 或 registry。OpenClaw adapter 负责把这些平台能力整理成 core 可调用的固定接口。

```text
Core/
  ↕ connector contract
Adapters/openclaw/
  ↕
OpenClaw runtime / plugin / session environment
```

一句话：OpenClaw adapter 把 OpenClaw 平台上的会话输入、模型调用、runtime hook、plugin 包装与 session watch 生命周期逻辑，整理成 `CONNECTOR.py` 暴露给 `Core/` 的稳定能力集合。

## 对外入口

```text
Adapters/openclaw/CONNECTOR.py
```

当前暴露：

| 接口 | 实现方向 |
| --- | --- |
| `ensure_config` | OpenClaw adapter config bootstrap |
| `memory_worker.call_llm` | 调用 OpenClaw worker runtime |
| `memory_worker.clean_runtime` | 清理 MW runtime / sessions |
| `memory_worker.prerequisites` / `install` / `uninstall` | MW 侧安装生命周期 |
| `production_agent.extract` | OpenClaw sessions -> Layer0 input |
| `production_agent.preserve` / `decay` | Sessions_Watch preserve / decay |
| `production_agent.prerequisites` / `install` / `uninstall` | PA 侧安装生命周期 |

## 能力域

| 目录 / 文件 | 职责 |
| --- | --- |
| `Extract/` | 读取 OpenClaw sessions、known-direct-sessions registry、`.jsonl` 文件，并归一化为 Layer0 输入 |
| `openclaw_call_LLM.py` | 把 Layer1 / Layer3 prompt 转成 OpenClaw MW session 执行 |
| `openclaw_runtime_maintenance.py` | 承接 `memory_worker.clean_runtime`，清理任务型 runtime 状态 |
| `Read/` | 把 `Core/Layer4_Read/` 包装成 OpenClaw plugin tools 与 plugin-shipped skills |
| `Sessions_Watch/` | 维护 OpenClaw active session registry，并承接 preserve / decay hook |
| `Installation/` | OpenClaw-specific prerequisites / install / uninstall |

## 支撑的 core 主链

Layer0：

```text
OpenClaw sessions / registry -> Adapters/openclaw/Extract -> Core/Layer0_Extract
```

Layer1 / Layer3 LLM：

```text
Core Layer1 / Layer3 -> memory_worker.call_llm -> openclaw_call_LLM.py -> OpenClaw MW runtime
```

Layer2 / Layer3 hook：

```text
Core Layer2 / Layer3 -> production_agent.preserve / decay -> Sessions_Watch
```

Layer4 read：

```text
Core/Layer4_Read -> Adapters/openclaw/Read -> OpenClaw plugin tools + skill
```

## Read 与 Layer4

读取逻辑本身属于 `Core/Layer4_Read/`。OpenClaw `Read/` 只负责平台包装：

- plugin `index.ts`
- plugin manifest
- recall tools
- plugin-shipped skill

当前 OpenClaw 集成形态是 **工具插件 + skill 引导**，不是 OpenClaw memory backend；不要把 `plugins.slots.memory` 指向 MemoquasarEterna。

## Sessions_Watch 与 preserve / decay

`Sessions_Watch/` 处理 OpenClaw 平台侧状态生命周期：

| 方向 | Core 侧 | OpenClaw 侧 |
| --- | --- | --- |
| Preserve | Layer2 archive memory surface | preserve session registry / session files |
| Decay | Layer3 trim / shallow / deep | 谨慎清理 session watch data |

生产 agent 原始 session 文件衰减默认关闭。只有理解风险后，才应在 `OpenclawConfig.json` 中开启 `sessions_registry_maintenance.session_files_decay`。

## 配置体系

| 配置 | 职责 |
| --- | --- |
| `OverallConfig.json` | harness 路由、agent 列表、code/store/archive、timezone/window、产品名 |
| `Adapters/openclaw/OpenclawConfig.json` | OpenClaw 路径模板、sessions、registry、maintenance、archive、preserve / decay 配置 |

仓库跟踪模板，本地运行读取实际 config。顶层 install 会自动生成缺失 config，并在 `schema_version` 不一致时提前中止。

## 当前成熟度

OpenClaw 是当前 production/default adapter。已经稳定落位：

- `CONNECTOR.py`
- Layer0 `Extract/`
- MW `call_llm`
- MW runtime cleanup
- Layer4 read plugin 模板与安装脚本
- `Sessions_Watch/` preserve / decay 业务域
- OpenClaw-specific install / uninstall

仍需谨慎看待：

- Sessions_Watch 的更激进 decay 功能默认关闭
- OpenClaw 主配置需要用户手动 merge `Installation/example-openclaw.json`
- MW 必须是专用内部 agent，不能与 PA 混用

## 推荐阅读顺序

1. `docs/A1_installation-guide.md`
2. `docs/B1_maintenance-guide.md`
3. `docs/C1_architecture.md`
4. `docs/C2_connector-contract.md`
5. `Adapters/openclaw/README.md`
6. `Adapters/openclaw/CONNECTOR.py`
7. 按需深入 `Extract/`、`Read/`、`Sessions_Watch/`

## 一句话总结

OpenClaw adapter 是当前最完整的 production harness：它承接会话输入、LLM 调用、runtime cleanup、Layer4 plugin 包装，以及 OpenClaw session watch 的 preserve / decay 生命周期。
