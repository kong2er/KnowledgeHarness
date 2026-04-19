# KnowledgeHarness Memory Index

> **非权威**：本目录是对话上下文的历史副本，仅作为参考背景。
> 仓库真实状态以 `docs/PROJECT_STATE.md` 为准；
> 开发规则以 `SKILL.md` + `docs/ACCEPTANCE.md` + `.codex/session_rules.md` 为准。
> 若本目录内容与上述权威文档冲突，以权威文档为准，并视为本目录待更新。

每次执行前建议按以下顺序读取：

1. `project_memory/01_readme_baseline.md`
2. `project_memory/02_skill_draft.md`
3. `project_memory/03_mvp_task_constraints.md`

## Hard Constraints (Execution Baseline)

- 用户资料优先，外部信息仅补充且必须标注链接。
- 严格流程顺序：解析 -> 切分 -> 分类 -> 总结 -> 重点提炼 -> 补充 -> 校验 -> 导出。
- 分类必须先于总结。
- 低置信度或冲突内容进入 `unclassified` / `review_needed`，不可强行合并。
- chunk 级问题进 `review_needed`；系统级警告进 `pipeline_notes`。两者不可混用。
- 输出必须保留来源信息（至少 `source_name` / `source_type` / `chunk_id` / `raw_text` / `extracted_text`）。
- 输出结构至少包含 `overview` / `categorized_notes` / `stage_summaries` / `key_points` / `web_resources` / `review_needed` / `pipeline_notes` / `validation`。
- 不编造事实，不静默丢弃未解决内容。

## Notes

- 本目录用于固定"对话中确认过的项目约束与规划"。
- 若后续约束变更，请在本目录新增版本文件并更新本索引；同时同步 `docs/PROJECT_STATE.md` 与 `docs/ACCEPTANCE.md`。
