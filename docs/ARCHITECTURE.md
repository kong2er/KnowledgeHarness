# ARCHITECTURE

## 主流程

```text
Input Files (txt/md/pdf/docx/png/jpg/jpeg)
  -> runtime_config     (JSON config merge with defaults)
  -> parse_inputs        (failed_sources w/ reason / empty_extracted_sources / ingestion_summary / notifier)
  -> chunk_notes
  -> topic_coarse_classify (document-level, constrained labels, optional API-assist)
  -> classify_notes      (categorized + review_needed)
  -> stage_summarize
  -> extract_keypoints
  -> web_enrichment      (off/local/api/auto; supplementary)
  -> detect_semantic_conflicts (heuristic)
  -> validate_result     (consumes failed_sources / empty_sources / web_resources / semantic_conflicts)
  -> assemble result     (review_needed ≠ pipeline_notes)
  -> export_notes
  -> outputs/result.json + outputs/result.md
```

## 模块关系

- `app.py`
  - 流程编排
  - 输入收集（文件 / 目录 / glob），默认跳过项目元目录
  - 读取运行时配置（`config/pipeline_config.json`）
  - 汇总统一 `result`，分离 `review_needed` 与 `pipeline_notes`

- `service/api_server.py`
  - FastAPI 最小服务入口
  - 暴露 `/health`、`/pipeline/run`、`/pipeline/capabilities`
  - 服务层只做请求封装，不改动核心流水线语义

- `tools/parse_inputs.py`
  - 输入标准化为文档对象
  - 支持 txt / md / pdf / docx；图片 `.png/.jpg/.jpeg` 走 opt-in OCR，缺失依赖时降级为 `ocr_backend_unavailable`
  - docx heading 样式感知：注入 `heading_path` 到段落文本
  - 失败文件不阻断全流程，进入 `logs.failed_sources`，条目携带 `reason`
  - 正文为空的文件进入 `logs.empty_extracted_sources`
  - 可选 `notifier(event, payload)` 回调驱动 CLI 阶段告知
  - 返回体附 `ingestion_summary`：本次运行的真实能力自报表
  - OCR 语言可配置（`ocr_languages`/`ocr_fallback_language`）

- `tools/runtime_config.py`
  - 加载 `config/pipeline_config.json`
  - 深度合并默认配置，失败时降级并输出 warning

- `tools/chunk_notes.py`
  - 文档 → chunks（段落→句→字符三级 fallback）
  - 继承来源信息并生成 `chunk_id`

- `tools/classify_notes.py`
  - chunks → categorized chunks
  - 关键词 + 起始标签双路打分
  - tie-break 走 `CATEGORY_PRIORITY`
  - 低置信度 → `unclassified` + `review_needed`
  - 支持通过配置注入关键词/提示词/优先级

- `tools/topic_coarse_classify.py`
  - documents → topic labels（source/document 粒度）
  - 受本地 taxonomy 约束（`config/topic_taxonomy.json`）
  - 模式：`auto/local/api`
  - API 为可选协助；越界标签、超时、错误均降级（local/unknown），并记录 warnings
  - 支持可配置重试次数（默认 1 次重试）

- `tools/web_enrichment.py`
  - 开关式补充资源生成（`off/local/api/auto`）
  - `local` 模式：从用户资料中提取 URL 并结构化
  - `api/auto` 模式：可选外部协助，失败回退 local/off
  - 严格资源 schema：`title/url/purpose/relevance_reason`

- `tools/detect_semantic_conflicts.py`
  - 基于声明关键词的最小冲突检测（必须/不需要、可以/不可以 等）
  - 输出冲突对（chunk_a/chunk_b + reason）

- `tools/stage_summarize.py`
  - 从分类结果生成三阶段摘要（三键始终存在）

- `tools/extract_keypoints.py`
  - 按 `BUCKET_ORDER` + `confidence desc` 组织并去重
  - 支持 `min_confidence` 阈值过滤
  - 支持 `max_points` 上限配置

- `tools/validate_result.py`
  - 对分类与摘要做一致性与完整性校验
  - 消费 parse 层的 failed/empty 记录

- `tools/export_notes.py`
  - 序列化为 JSON 与 Markdown
  - `review_needed` / `pipeline_notes` / `failed_sources` / `empty_sources` 分区呈现

## 数据契约（顶层 result）

```text
{
  "overview": {
    source_count, chunk_count,
    failed_sources,              # each: {source, source_name, source_type, reason, error}
    empty_extracted_sources,
    ingestion_summary,           # detected/supported/unsupported/succeeded/
                                 # empty_extracted/failed/breakdown_by_type/
                                 # supported_extensions_effective/image_extensions_opt_in/
                                 # ocr_backend
  },
  "source_documents":    [ ... ],
  "topic_classification": {
    mode_requested, allowed_labels, label_definitions,
    items: [ {source_name, topic_label, confidence, reason, used_api, api_attempts, fallback_state}, ... ],
    topic_groups, stats, warnings
  },
  "categorized_notes":   { <category>: [ chunk, ... ] },
  "stage_summaries":     { stage_1, stage_2, stage_3 },
  "key_points":          { key_points: [...], stats: {...} },
  "web_resources":       [ {title, url, purpose, relevance_reason}, ... ],
  "semantic_conflicts":  [ {reason, chunk_a, chunk_b, ...}, ... ],
  "review_needed":       [ chunk-level items only ],
  "pipeline_notes":      [ system-level messages, e.g. "no usable input text", validation warnings ],
  "validation":          { is_valid, warnings, stats },
  "export_paths":        { json_path, md_path }
}
```

## 当前设计原则

- 用户资料优先
- 分类先于总结
- 主题粗分类与内容功能分类分层解耦
- 失败降级，不中断主流程
- 输出可追溯（保留来源信息）
- chunk 级问题 ≠ 系统级警告：前者入 `review_needed`，后者入 `pipeline_notes`

## 当前边界

- 外部补充可开关，且失败降级不影响主流程
- 已有最小 FastAPI 服务入口；Flask 与生产级鉴权/限流/任务队列未实现
- 无测试框架层
- 无高级（NLI/向量）语义冲突检测
