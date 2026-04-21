# Session Rules (Long-Run Mandatory)

本文件用于把“长期工程执行代理”工作方式固化为可复用流程。
目标：不依赖长聊天上下文，而依赖仓库内权威文档持续推进项目。

---

## 1) 权威层级与记忆策略

### 一级权威（必须优先读取）
1. `README.md`
2. `SKILL.md`
3. `docs/PROJECT_STATE.md`

### 二级权威（任务与验收约束）
4. `docs/ACCEPTANCE.md`
5. `docs/TODO.md`
6. `docs/ARCHITECTURE.md`
7. `docs/HANDOFF.md`
8. `docs/ENGINEERING_REVIEW.md`

### 三级记忆（仅补充参考）
9. `project_memory/*`（历史快照，非权威）

### 冲突处理顺序（从高到低）
1. `docs/PROJECT_STATE.md`（事实）
2. `SKILL.md` / `docs/ACCEPTANCE.md`（规则）
3. `docs/ARCHITECTURE.md` / `README.md`（说明）
4. `project_memory/*` / 聊天上下文（参考）

禁止把聊天记忆或 `project_memory/*` 当成事实真相源覆盖权威文档。

---

## 2) Pre-Change Gate（改动前强制执行）

任何代码/文档改动前，必须先输出“读取摘要”，至少包含：
1. 已实现核心能力
2. 明确未实现能力
3. 当前任务与项目边界是否冲突
4. 本次计划修改文件
5. 本次明确不改范围
6. 本次完成后需同步的文档

且必须先判断本次任务类型（至少一类）：
- 输入层
- 中间计算层
- 校验层
- 输出层
- 测试基础设施
- 文档治理层
- 打包/交付层

若分类不清，先说明判断依据，再编码。

---

## 3) 长任务阶段压缩（Short-Term Memory Control）

满足任一条件时，必须做“阶段总结”并写回文档：
1. 一次任务包含多个子步骤
2. 修改文件数 > 3
3. 完成一个子模块
4. 准备切换到下一个模块

阶段总结至少包含：
1. 本阶段完成项
2. 变更文件清单
3. 真实现 vs 占位能力
4. 当前已知问题
5. 下一步建议
6. 是否影响 demo/验收线

---

## 4) 文档写回触发器（Long-Term Memory Writeback）

出现以下任一情况，必须同步文档：
1. 新增模块
2. 模块职责变化
3. 子阶段完成
4. 验收结果变化
5. 真实状态变化
6. 依赖变化
7. 新失败语义/降级策略

最低写回要求：
- `docs/PROJECT_STATE.md`：真实状态
- `docs/TODO.md`：完成/未完成项
- `docs/HANDOFF.md`：下一步建议
- `docs/ACCEPTANCE.md`：若影响验收规则则更新

---

## 5) 上下文恢复模式（会话过长或不可靠时）

若会话变长、信息冲突、边界不清，必须：
1. 暂停直接编码
2. 回读一级/二级权威文档
3. 输出“上下文恢复摘要”
4. 必要时先修正文档再继续

上下文恢复摘要必须包含：
- 项目目标
- 已完成模块
- 未完成模块
- 当前任务位置
- 不能越界的边界

---

## 6) 输出规范（默认工作节奏）

进入开发任务时默认按以下结构输出：
1. 读取摘要
2. 变更范围声明
3. 设计说明
4. 文件修改
5. 阶段总结
6. 文档写回摘要
7. 当前真实支持能力总结

若仅讨论方案，也至少输出：
- 读取摘要
- 变更范围声明

---

## 7) 停止扩展条件（防漂移）

出现以下任一情况必须停止功能扩展并先治理：
1. 文档与代码不一致
2. 验收条目无法映射到当前改动
3. 任务边界不清或明显越界
4. 未完成阶段总结却准备进入新模块

---

## 8) Post-Change Gate（宣告完成前）

任务宣告完成前，必须：
1. 按 `docs/ACCEPTANCE.md` §3 + 受影响模块 §4 自检
2. 至少跑通：`python3 app.py samples/demo.md --output-dir outputs --quiet`（或 `./scripts/run_acceptance_gate.sh`）
3. 明确 `validation.is_valid` 与 warnings
4. 完成对应文档写回（PROJECT_STATE / TODO / HANDOFF / ACCEPTANCE）
