# ARCHITECTURE

## 交付面板（同一条核心流水线 × 5 种调用方式）

| 交付面 | 入口 | 定位 |
|--------|------|------|
| CLI | `app.py` | 权威入口；所有 flag 与配置由此驱动；所有测试与 Docker 都复用它 |
| FastAPI | `service/api_server.py` (`/pipeline/run` 等) | 可选依赖（`requirements-api.txt`）；薄包装，不分叉核心逻辑 |
| Flask | `service/flask_server.py` (`/pipeline/run` 等) | 可选依赖（`requirements-flask.txt`）；请求 schema 与 FastAPI 入口对齐 |
| Local Web UI | `service/simple_ui.py` | 零第三方依赖（stdlib `http.server`）；文件池、上传限额、下载端点、masked API key |
| Docker | `Dockerfile` | OCR-ready：容器内已装 `tesseract-ocr` + `tesseract-ocr-chi-sim`，同时保留 CLI/API/UI 全部入口 |

所有入口最终都走 `app.run_pipeline`，所以 CLI 上验收过的行为 = 其他面的行为。

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
  -> export_notes        (final_notes_only | full_report)
  -> [optional] export_word (from rendered result.md)
  -> outputs/result.json + outputs/result.md [+ result.docx]
```

## 模块关系

- `app.py`
  - 流程编排
  - 输入收集（文件 / 目录 / glob），默认跳过项目元目录（含 `uploads/`）
  - 读取运行时配置（`config/pipeline_config.json`）
  - 自动加载项目根 `.env`（不覆盖已存在的系统环境变量）
  - API 协助编排：默认关闭；仅在显式开启时允许 auto 模式使用外部 API
  - 汇总统一 `result`，分离 `review_needed` 与 `pipeline_notes`
  - `final_notes_only` / `export_docx` 等笔记形态开关

- `service/api_server.py`
  - FastAPI 最小服务入口
  - 暴露 `/health`、`/pipeline/run`、`/pipeline/capabilities`
  - 服务层只做请求封装，不改动核心流水线语义

- `service/flask_server.py`
  - Flask 最小服务入口
  - 暴露 `/health`、`/pipeline/run`、`/pipeline/capabilities`
  - 请求字段默认值与 `service/api_server.py` 对齐，服务层不分叉核心逻辑

- `launch_app.py`
  - 桌面启动器：启动 `service/simple_ui.py` 同款 UI 服务并自动打开浏览器
  - 用于“直接打开软件”式交付（配合 PyInstaller 打包）

- `service/simple_ui.py`
  - 基于 stdlib `http.server` 的本地 Web UI，**零第三方依赖**（不使用已废弃的 `cgi` 模块）
  - 路由：`GET /`、`GET /settings`、`POST /run`、`POST /settings`、`POST /uploads/clear`、`POST /uploads/remove`、`GET /download?name=…`
  - 文件池（`uploads/ui_uploads/`）+ 类型 pill + 计数汇总；prev 上传可勾选重跑
  - 上传四重限额：图片数 / 总数 / 单文件大小 / 请求体大小
  - `/download` 严格限制在 `<ROOT>/outputs/` 下；双层校验（正则白名单 + `Path.relative_to`）
  - `/settings` 密钥字段永不回显，只展示 masked 状态（末 4 位）；留空提交=保持原值
  - 相对输出目录以 `ROOT` 为基准解析，UI 实时显示"本次将写入"的绝对路径

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
  - API 协议风格：`custom` / `openai_compatible` / `auto`
  - API 为可选协助；越界标签、超时、错误均降级（local/unknown），并记录 warnings
  - 支持可配置重试次数（默认 1 次重试）

- `tools/web_enrichment.py`
  - 开关式补充资源生成（`off/local/api/auto`）
  - `local` 模式：从用户资料中提取 URL 并结构化
  - `api/auto` 模式：可选外部协助，失败回退 local/off
  - API 协议风格：`custom` / `openai_compatible` / `auto`
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
  - 消费 parse 层的 failed/empty 记录、web enrichment 资源、语义冲突

- `tools/export_notes.py`
  - 序列化为 JSON 与 Markdown
  - `final_notes_only=True`（默认）：清洗 classifier-facing 噪声（前缀冠词、`[heading_path: …]` 尾巴），多源自动加来源注释，自适应决定是否输出"重点速记"节
  - `final_notes_only=False`：完整报告版（Stage 1/2/3 + ingestion + topic + conflicts）
  - `review_needed` / `pipeline_notes` / `failed_sources` / `empty_sources` 分区呈现

- `tools/export_word.py`
  - 从已生成的 `result.md` 转换为 `result.docx`
  - 覆盖 `_render_final_notes_markdown` 实际输出的子集：headings / bullets / quote / horizontal rule / inline italic
  - 失败只记 `pipeline_notes`，不中断主流程

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
- 已有最小 FastAPI / Flask 服务入口；生产级鉴权/限流/任务队列未实现
- 无测试框架层
- 无高级（NLI/向量）语义冲突检测
- 全局工程审计与路线维护放在 `docs/ENGINEERING_REVIEW.md`（阶段性更新）

## 工程门禁入口

- 推荐在变更完成后执行 `./scripts/run_acceptance_gate.sh`：
  - 统一跑 7 份 stdlib 测试
  - 统一跑 `samples/demo.md` smoke
  - 统一验证 `result.json` 顶层契约与 demo 有效性
