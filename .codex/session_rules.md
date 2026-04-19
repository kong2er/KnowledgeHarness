# Session Rules (Mandatory)

从本项目当前会话开始，任何代码修改前必须先读取并理解以下文件：

1. `README.md`
2. `SKILL.md`
3. `docs/PROJECT_STATE.md`
4. `docs/ACCEPTANCE.md`

权威来源顺序（冲突时从上往下覆盖）：

1. `docs/PROJECT_STATE.md`（事实）
2. `SKILL.md` / `docs/ACCEPTANCE.md`（规则）
3. `docs/ARCHITECTURE.md` / `README.md`（说明）
4. `project_memory/*`（历史对话副本，**非权威**）

## Pre-Change Gate

在开始改代码前，必须先输出"读取摘要"，至少包含：

- 当前项目边界（已实现 / 未实现）
- 本次修改范围（将修改哪些文件、不会修改哪些范围）
- 与现有约束是否冲突
- 将通过 `docs/ACCEPTANCE.md` 中哪些 Gate（G0–G3）以及对应的模块级条目

若发现文档与代码不一致：

- 先修正文档与代码的一致性
- 再继续本次任务

## Post-Change Gate

任务宣告完成前，必须：

- 按 `docs/ACCEPTANCE.md` §3 通用 Gate 和受影响模块的 §4 条目逐条自检
- 至少在 `samples/demo.md` 上跑通 `python3 app.py`，确认 `is_valid == True`
- 同步更新 `docs/PROJECT_STATE.md` 与 `docs/TODO.md`

禁止只依赖历史对话记忆推进项目。
禁止把 `project_memory/*` 作为事实依据凌驾于 `docs/PROJECT_STATE.md` 之上。
