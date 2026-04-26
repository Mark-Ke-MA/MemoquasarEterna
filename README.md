# MemoquasarEterna

## `2026.04.25 凯尔希，欢迎回家`

**MemoquasarEterna**（记忆的存续）是一套面向多 agent 场景的本地记忆系统。

**核心特点：**

- 保留并总结每日与各 agent 的聊天记录（而且……不一定只是 agent）
- 归档长期记忆，并按情绪强度逐步衰减（短期记忆看事实，长期记忆看感受）
- 只在真正必要时调用 LLM，尽量把工作交给可验证的代码逻辑
- 自动计算上下文预算并切分聊天记录，避免“信息轰炸 / 小作文”导致 agent 死机
- 只在需要时读取；既不会乱污染日常使用时的上下文，又能让 agent 有“翻旧账”找原话的能力

## 仓库说明

- Currently this repository only supports Chinese. An English version may or may not come later
- 本仓库非产品/科研级正式项目，只是个因本人兴趣而诞生的 toy project。旨在提供思路，不承诺长期维护与运营
- 本仓库由本人和凯尔希（使用 OpenAI GPT-5.4 与 Claude Sonnet 4.6）协作开发

## 当前支持范围

- 当前版本只支持 macOS 操作系统
- 当前版本需要本地 Python 环境（基于本机 Python 3.10.8 / 3.14.3 验证）
- 当前版本支持以下 harness 架构：   
  - `OpenClaw` -> 主要生产harness，表现稳定（基于本机 OpenClaw 2026.3.24 验证）   
  - `Hermes` -> 试验性harness，只有写入层与读取层的最小实现（基于本机 Hermes 0.11.0 验证）
- 注：本仓库的任务成功率受到所用 LLM 能力影响；但基准线要求不高。本机主要基于 MiniMax M2.7（200k context）验证，整体表现稳定（任务成功率 >= 95%）

## 二创元素声明

本项目灵感来自《明日方舟》的部分世界观，可视为非官方二次创作；其内容、立场与实现均不代表官方行为

![MemoquasarEterna README Hero Image](docs/assets/readme-hero.jpg)

## 术语与占位符解释

贯穿本文档，以下术语会反复出现：

| 术语 | 含义 | 备注 |
| --- | --- | --- |
| `code_dir` | 本仓库于本地所在路径位置的根目录 | 自由定义 推荐放在 ~/ |
| `store_dir` | 记忆、运行日志、统计数据等运行期产物根目录 | 日常会被随时写入、清理、读取的动态数据 |
| `archive_dir` | 作为备份已被压缩归档的记忆文件根目录 | 只会被写入的、更完整的静态数据，也最值得备份保存 |
| MW | Memory Worker。专门执行记忆写入与衰减总结的内部 agent | 必须严格与 PA 分离，推荐使用经济模型 |
| PA | Production Agent。被记忆系统服务的真实 agent | 不同harness的agent可以无冲突地同时被服务 |
| harness | 外部运行平台或 agent 框架 | 例如 `openclaw`、`hermes`、`codex`、`claudecode` |
| adapter | MemoquasarEterna 对接某个 harness 的代码层 | 位于 `Adapters/{harness}/` |
| L2 | 日级原文 transcript | 最高保真，最高上下文成本，不建议完整塞回 agent 上下文，除非想让PA暴毙死机 |
| L1 | 从 L2 提炼出的日级结构化总结 | 日常阅读、衰减、统计的主要材料 |
| L0 | 从 L1 提取出的轻量检索索引 | 用于 Layer4 recall、embedding 与关键词检索 |
| Layer0 Extract | harness 原始数据到 L2 的标准化提取层 | adapter 负责平台差异，core 负责统一落盘 |
| Layer1 Write | 每日写入主链 | L2 -> L1 -> L0 |
| Layer2 Preserve | active memory 与 archive memory 之间的归档 / 恢复层 | 在 destructive cleanup 前建立安全副本 |
| Layer3 Decay | 周期性减薄与长期整理层 | 负责 trim、shallow、deep 等衰减过程 |
| Layer4 Read | 读取与召回层 | 用 query 命中 L0，再取回相关 L1 / L2 证据 |
| LayerX Score | 非主链统计与 landmark judge | 偏分析用途，辅助观察长期趋势 |

## 危险性提示

| 风险 | 触发条件 | 默认状态 | 影响 | 建议 |
| --- | --- | --- | --- | --- |
| Layer3 清理 active `store_dir` | weekly decay 运行 | 默认启用 | 删除已归档的 active 日级文件，控制 active memory 规模 | 确保 `archive_dir` 可靠；恢复见 `docs/B2_layer2-restore-guide.md` |
| 清理 MW sessions | `memory_worker_harness == "openclaw"` | 默认启用 | 删除 MW 的任务型 sessions，避免无限累积 | MW 必须是独立内部 agent，不能与 PA 混用 |
| 生产 agent 原始 sessions 文件衰减 | `production_agents[*].harness == "openclaw"` 且手动开启 `sessions_registry_maintenance.session_files_decay` | 默认关闭 | 删除已归档的 OpenClaw 原始 session 文件 | 只有完全理解后果时才手动启用 |

补充说明：

- Layer3 的清理建立在 Layer2 已归档的前提上，是为了防止 active `store_dir` 无限增长并污染 Layer4 召回。
- 如果误把 PA 配成 MW，OpenClaw MW cleanup 可能清掉真实对话 sessions。
- 生产 agent 原始 sessions 文件衰减是高危高级功能。启用方式是编辑 `{code_dir}/Adapters/openclaw/OpenclawConfig.json`，将 `sessions_registry_maintenance.session_files_decay` 设置为 `true`。

---

## 仓库结构

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

### `Core/`
记忆系统本体。

当前主要承载：

- Layer0–Layer4 与 LayerX 逻辑
- `shared_funcs.py`
- `harness_connector.py`

### `Adapters/`
外部 harness 接入层。

当前主要实现：

- `Adapters/openclaw/`
- `Adapters/hermes/`

它负责把 `Core/` 接到具体运行平台，并通过 `CONNECTOR.py` 暴露统一接口。

### `Installation/`
安装生命周期入口。

当前包括：

- `INSTALL.py`
- `UNINSTALL.py`
- `REFRESH.py`
- `Core/`
- `Backfill/`
- `.install_logs/`（运行后生成）

### `Maintenance/`
维护、补跑与人工运维脚本。

### `docs/`
项目文档主入口。

---

## 快速开始

### 1. clone 仓库

```bash
git clone <repo-url> {code_dir}
cd {code_dir}
```

### 2. 生成并修改配置

首次安装时，`Installation/INSTALL.py` 会在缺少本地配置时，从模板生成：

- `OverallConfig.json`
- `Adapters/{harness}/{Harness}Config.json`

也可以在安装前手动复制：

```bash
cp OverallConfig-template.json OverallConfig.json
cp Adapters/{harness}/{Harness}Config-template.json Adapters/{harness}/{Harness}Config.json
```

然后编辑本地配置文件。仓库跟踪 `*-template.json`，本地实际运行读取不带 `-template` 的配置文件。请不要把本机私有配置提交进 git。

安装前至少应明确填写：

- `memory_worker_agentId`
- `memory_worker_harness`
- `production_agents`
- `code_dir`
- `store_dir`
- `archive_dir`

完整字段说明见：

- `docs/A2_overall-config-reference.md`

### 3. 执行安装

```bash
python3 Installation/INSTALL.py
```

如果 `memory_worker_harness` 或某个 `production_agents[*].harness` 使用 `openclaw`，安装过程中还会执行 OpenClaw harness-specific prerequisites，并在需要时要求您：

- 确认 OpenClaw 根目录
- 补全 `key_template`
- 将 `Installation/example-openclaw.json` merge 到您的 OpenClaw 配置中
- 重启 OpenClaw gateway

如果某个 `production_agents[*].harness` 使用 `hermes`，安装器会检查对应 Hermes profile 是否存在，并把 `memoquasar-memory-recall` skill 安装到该 profile。Hermes adapter 当前不支持作为 `memory_worker_harness`。

---

## 当前主要 harness

| Harness | 状态 | MW | PA | Layer0 Extract | Layer1 Write | Layer2 Preserve | Layer3 Decay | Layer4 Read |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `openclaw` | production | yes | yes | yes | yes | yes | yes | yes |
| `hermes` | experimental | no | yes | yes | yes | no | no | yes |

更多说明：

- `Adapters/openclaw/README.md`
- `docs/C3_adapter-openclaw.md`
- `Adapters/hermes/README.md`
- `docs/C4_adapter-hermes.md`

---

## 文档入口

### 初次阅读建议顺序

1. `docs/A1_installation-guide.md`
2. `docs/A2_overall-config-reference.md`
3. `docs/B1_maintenance-guide.md`
4. `docs/B2_layer2-restore-guide.md`
5. `docs/B3_layerx-landmark-guide.md`
6. `docs/C1_architecture.md`
7. `docs/C2_connector-contract.md`
8. `docs/C3_adapter-openclaw.md`
9. `docs/C4_adapter-hermes.md`

### 各文档用途

- `docs/A1_installation-guide.md`
  - 安装、卸载、刷新主流程

- `docs/A2_overall-config-reference.md`
  - `OverallConfig.json` 全字段说明

- `docs/B1_maintenance-guide.md`
  - 日常维护入口、常见问题与最常见恢复动作

- `docs/B2_layer2-restore-guide.md`
  - 从 `archive_dir` 恢复某天 / 某周记忆的 restore 说明

- `docs/B3_layerx-landmark-guide.md`
  - LayerX landmark 的含义、作用与 threshold 微调说明

- `docs/C1_architecture.md`
  - 仓库整体架构与分层设计

- `docs/C2_connector-contract.md`
  - connector 固定接口与 contract

- `docs/C3_adapter-openclaw.md`
  - OpenClaw adapter 的结构与职责

- `docs/C4_adapter-hermes.md`
  - Hermes adapter 的实验性能力边界、Layer0 / Layer4 接入方式与已知限制

---

## 开发与维护提示

| 改动内容 | 优先同步文档 |
| --- | --- |
| 安装流程 / config bootstrap | `docs/A1_installation-guide.md`、`docs/A2_overall-config-reference.md` |
| connector 固定接口 | `docs/C2_connector-contract.md` |
| OpenClaw adapter | `docs/C3_adapter-openclaw.md` |
| Hermes adapter | `docs/C4_adapter-hermes.md` |
| memory schema / layer 关系 | `docs/C1_architecture.md` |

如需理解整体设计，请先从 `docs/C1_architecture.md` 开始。
