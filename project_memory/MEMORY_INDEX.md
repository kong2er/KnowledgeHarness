# KnowledgeHarness Memory Index

每次执行前建议按以下顺序读取：

1. `project_memory/01_readme_baseline.md`
2. `project_memory/02_skill_draft.md`
3. `project_memory/03_mvp_task_constraints.md`

## Hard Constraints (Execution Baseline)

- 用户资料优先，外部信息仅补充且必须标注链接。
- 严格流程顺序：解析 -> 切分 -> 分类 -> 总结 -> 重点提炼 -> 补充 -> 校验 -> 导出。
- 分类必须先于总结。
- 低置信度或冲突内容进入 `unclassified`/`review_needed`，不可强行合并。
- 输出必须保留来源信息（至少 source_name/source_type/chunk_id/raw_text/extracted_text）。
- 输出结构至少包含 overview/categorized notes/stage summaries/key points/web resources/review_needed。
- 不编造事实，不静默丢弃未解决内容。

## Notes

- 本目录用于固定“对话中确认过的项目约束与规划”。
- 若后续约束变更，请在本目录新增版本文件并更新本索引。
