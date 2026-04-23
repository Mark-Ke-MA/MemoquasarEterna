# Layer2 Restore 指引

本文档说明如何使用 Layer2 的 restore 入口，从 `archive_dir` 中恢复指定日期或周的记忆文件。

## 这份文档解决什么问题
当 Layer3 已经对 active `store_dir` 做过正常清理，而你又希望重新查看、比对或取回某天记忆时，可以使用 Layer2 restore。

它的核心入口是：
```bash
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py
```

## restore 前要知道什么
- restore 依赖 `archive_dir` 中已经存在对应归档
- restore 主要用于恢复已归档内容，不是日常高频操作
- 默认推荐先用 `mirrored` 模式，这样更保守

## 常用参数
- `--week`：目标 ISO week，例如 `2026-W15`
- `--date`：目标日期，例如 `2026-04-14`
- `--agent`：只处理指定 agent；支持逗号分隔多个 agent
- `--which-level`：恢复粒度，默认 `all`；也支持 `l0` / `l1` / `l2` / 逗号列表
- `--restore-mode`：`mirrored` / `update` / `overwrite`
- `--run-name`：可选；为这次 restore 指定 run 名称
- `--clear`：清理 restored 目录内容，支持 `all` 或某个 `run_name`

## 推荐用法

### 1. 先做保守恢复（推荐）
按日期恢复，并使用默认 `mirrored` 模式：
```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --date 2026-04-14
```

按周恢复：
```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --week 2026-W15
```

只恢复某个 agent：
```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --date 2026-04-14 --agent kaltsit
```

### 2. 指定恢复层级
例如只恢复 `l1`：
```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --date 2026-04-14 --which-level l1
```

### 3. 使用更激进的 restore 模式
如果你明确知道自己在做什么，可以改用：
- `update`
- `overwrite`

例如：
```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --date 2026-04-14 --restore-mode update
```

注意：`update` / `overwrite` 比 `mirrored` 风险更高，应只在你明确理解其影响时使用。

## restore 后的结果在哪里
restore 相关内容会进入：
```text
{store_dir}/restored/
```

你也可以在 restore log 中查看本次恢复了哪些文件。

## 清理 restored 内容
如果你只想清理 restore 产物，而不动根目录，可以使用：

清空全部 restored 内容：
```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --clear all
```

只清理某个 restore run：
```bash
cd {code_dir}
python Core/Layer2_Preserve/ENTRY_LAYER2_restore.py --clear <run_name>
```

## 常见建议
- 优先使用 `mirrored` 模式
- 先按单天、单 agent 小范围恢复，再决定是否扩大范围
- 如果你只是想确认某天是否已被归档，先检查 `archive_dir`，不要一上来就做大范围 restore
- 如果你不确定 restore 是否必要，先阅读：
  - `docs/B1_maintenance-guide.md`

## 一句话
Layer2 restore 的目标不是替代日常 active memory，而是在“已归档、已清理、但需要找回”的场景下，为你提供一个可控的恢复入口。
