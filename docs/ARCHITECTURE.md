# ARCHITECTURE

## 主流程

```text
Input Files
  -> parse_inputs        (failed_sources / empty_extracted_sources)
  -> chunk_notes
  -> classify_notes      (categorized + review_needed)
  -> stage_summarize
  -> extract_keypoints
  -> (web enrichment placeholder, returns [])
  -> validate_result     (consumes failed_sources / empty_sources)
  -> assemble result     (review_needed ≠ pipeline_notes)
  -> export_notes
  -> outputs/result.json + outputs/result.md
```

## 模块关系

- `app.py`
  - 流程编排
  - 输入收集（文件 / 目录 / glob），默认跳过项目元目录
  - 汇总统一 `result`，分离 `review_needed` 与 `pipeline_notes`

- `tools/parse_inputs.py`
  - 输入标准化为文档对象
  - 失败文件不阻断全流程，进入 `logs.failed_sources`
  - 正文为空的文件进入 `logs.empty_extracted_sources`

- `tools/chunk_notes.py`
  - 文档 → chunks（段落→句→字符三级 fallback）
  - 继承来源信息并生成 `chunk_id`

- `tools/classify_notes.py`
  - chunks → categorized chunks
  - 关键词 + 起始标签双路打分
  - tie-break 走 `CATEGORY_PRIORITY`
  - 低置信度 → `unclassified` + `review_needed`

- `tools/stage_summarize.py`
  - 从分类结果生成三阶段摘要（三键始终存在）

- `tools/extract_keypoints.py`
  - 按 `BUCKET_ORDER` + `confidence desc` 组织并去重

- `tools/validate_result.py`
  - 对分类与摘要做一致性与完整性校验
  - 消费 parse 层的 failed/empty 记录

- `tools/export_notes.py`
  - 序列化为 JSON 与 Markdown
  - `review_needed` / `pipeline_notes` / `failed_sources` / `empty_sources` 分区呈现

## 数据契约（顶层 result）

```text
{
  "overview":            { source_count, chunk_count, failed_sources, empty_extracted_sources },
  "source_documents":    [ ... ],
  "categorized_notes":   { <category>: [ chunk, ... ] },
  "stage_summaries":     { stage_1, stage_2, stage_3 },
  "key_points":          { key_points: [...], stats: {...} },
  "web_resources":       [],                # placeholder in MVP
  "review_needed":       [ chunk-level items only ],
  "pipeline_notes":      [ system-level messages ],
  "validation":          { is_valid, warnings, stats },
  "export_paths":        { json_path, md_path }
}
```

## 当前设计原则

- 用户资料优先
- 分类先于总结
- 失败降级，不中断主流程
- 输出可追溯（保留来源信息）
- chunk 级问题 ≠ 系统级警告：前者入 `review_needed`，后者入 `pipeline_notes`

## 当前边界

- 外部补充未接入，不参与主流程实算
- 无服务端 API 层
- 无测试框架层
- 无语义冲突检测
