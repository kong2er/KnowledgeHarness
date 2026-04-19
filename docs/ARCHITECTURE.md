# ARCHITECTURE

## 主流程

```text
Input Files
  -> parse_inputs
  -> chunk_notes
  -> classify_notes
  -> stage_summarize
  -> extract_keypoints
  -> (web enrichment placeholder)
  -> validate_result
  -> export_notes
  -> outputs/result.json + outputs/result.md
```

## 模块关系

- `app.py`
  - 流程编排
  - 输入收集（文件/目录/glob）
  - 汇总统一 `result`

- `tools/parse_inputs.py`
  - 输入标准化为文档对象
  - 失败文件不阻断全流程

- `tools/chunk_notes.py`
  - 文档 -> chunks
  - 继承来源信息并生成 `chunk_id`

- `tools/classify_notes.py`
  - chunks -> categorized chunks
  - 低置信度 -> `unclassified` + `review_needed`

- `tools/stage_summarize.py`
  - 从分类结果生成三阶段摘要

- `tools/extract_keypoints.py`
  - 从分类结果提炼复习重点

- `tools/validate_result.py`
  - 对分类与摘要做一致性和完整性校验

- `tools/export_notes.py`
  - 序列化为 JSON 与 Markdown

## 当前设计原则

- 用户资料优先
- 分类先于总结
- 失败降级，不中断主流程
- 输出可追溯（保留来源信息）

## 当前边界

- 外部补充未接入，不参与主流程实算
- 无服务端 API 层
- 无测试框架层
