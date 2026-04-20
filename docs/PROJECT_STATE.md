# PROJECT_STATE

Last Updated: 2026-04-20

## 1) Current Project Structure

```text
KnowledgeHarness/
├── .codex/
│   └── session_rules.md
├── .gitignore
├── .env.example
├── README.md
├── SKILL.md
├── requirements-api.txt             # FastAPI service deps (optional)
├── app.py
├── requirements.txt
├── requirements-ocr.txt             # opt-in OCR backend
├── config/
│   ├── topic_taxonomy.json          # constrained topic label set
│   ├── api_payload_templates.json   # default API prompt/payload contract
│   └── pipeline_config.json         # runtime pipeline config
├── Dockerfile
├── .dockerignore
├── docs/
│   ├── ACCEPTANCE.md
│   ├── API_SETUP.md
│   ├── ARCHITECTURE.md
│   ├── API_SETUP.md
│   ├── HANDOFF.md
│   ├── PROJECT_STATE.md
│   └── TODO.md
├── tools/
│   ├── __init__.py
│   ├── parse_inputs.py
│   ├── chunk_notes.py
│   ├── classify_notes.py
│   ├── detect_semantic_conflicts.py
│   ├── topic_coarse_classify.py
│   ├── web_enrichment.py
│   ├── runtime_config.py
│   ├── stage_summarize.py
│   ├── extract_keypoints.py
│   ├── validate_result.py
│   └── export_notes.py
├── service/
│   ├── api_server.py                # minimal FastAPI service entry
│   └── simple_ui.py                 # minimal local web inspection UI (stdlib)
├── tests/
│   ├── __init__.py
│   ├── test_parse_inputs.py         # stdlib-only; runs via `python3 tests/...`
│   ├── test_topic_coarse_classify.py
│   ├── test_stage1_core.py
│   ├── test_phase2_features.py
│   ├── test_phase3_non_api.py
│   └── test_api_service_entry.py
├── samples/
│   ├── demo.md
│   ├── ingest_demo.docx             # docx happy path
│   ├── ingest_demo.png               # image; triggers OCR or degrade
│   └── unsupported_demo.log          # unsupported_file_type path
├── outputs/                          # gitignored; run artifacts only
│   ├── result.json
│   └── result.md
└── project_memory/                   # historical chat context, non-authoritative
    ├── 01_readme_baseline.md
    ├── 02_skill_draft.md
    ├── 03_mvp_task_constraints.md
    └── MEMORY_INDEX.md
```

## 2) Implemented Modules

- `tools/parse_inputs.py`
  - txt / md（stdlib）
  - pdf（`pypdf`，懒加载）
  - docx（`python-docx`，懒加载）
  - docx heading 样式感知：抽取层级并注入 `heading_path`
  - **图片 `.png` / `.jpg` / `.jpeg`：opt-in OCR**，探测 `pytesseract` + `Pillow` + `tesseract` 二进制三者齐全才走真 OCR；任一缺失则 `failed_sources[*].reason = "ocr_backend_unavailable"`（不伪装成功）
  - 失败源统一 schema：`{source, source_name, source_type, reason, error}`；`reason` 取值 `unsupported_file_type / file_not_found / parse_error / ocr_backend_unavailable`
  - 可选 `notifier(event, payload)` 回调：事件 `detected / start / success / failed / summary`
  - 支持 OCR 语言配置：`ocr_languages` / `ocr_fallback_language`
  - 返回新增 `ingestion_summary`：`detected / supported / unsupported / succeeded / empty_extracted / failed / breakdown_by_type / supported_extensions_effective / image_extensions_opt_in / ocr_backend`

- `tools/chunk_notes.py`
  - 按空行分段
  - 长段按句切分（CJK 友好，不依赖句末空白）
  - 单句仍超 `max_chars` 时按字符硬切
  - 保留来源元数据并生成稳定 `chunk_id`

- `tools/classify_notes.py`
  - 关键词规则分类
  - 起始标签（`^xxx：`）给予 +3 强信号加成
  - tie-break 走 `CATEGORY_PRIORITY`（pitfalls > reading > methods > examples > concepts）
  - 分步 confidence 映射（1 / 2 / 3 / ≥4 → 0.4 / 0.6 / 0.85 / 1.0）
  - 低置信度 / 无关键词命中 → `unclassified` + `review_needed`
  - 支持从配置注入 `keywords` / `label_hints` / `category_priority`

- `tools/topic_coarse_classify.py`
  - 文档级（source/document 粒度）主题粗分类，不替代 chunk 级功能分类
  - 本地受约束标签集合来自 `config/topic_taxonomy.json`
  - 支持 `mode=auto/local/api`
  - 支持 API 重试（`api_retries`）
  - API 输出必须落在 allowed labels 内；越界/失败/超时降级到 local/`unknown_topic`
  - 输出 `topic_classification.items/topic_groups/stats/warnings`

- `tools/runtime_config.py`
  - 加载并深度合并运行时配置（`config/pipeline_config.json`）
  - 配置异常时回退默认值并产生 warning

- `tools/web_enrichment.py`
  - 可开关 enrichment（`enabled + off/local/api/auto`）
  - local 模式从用户资料抽取 URL；api/auto 失败回退 local/off
  - 输出资源 schema：`title/url/purpose/relevance_reason`

- `tools/detect_semantic_conflicts.py`
  - 启发式冲突检测（声明关键词互斥）
  - 输出冲突对（`chunk_a/chunk_b/reason`）

- `tools/stage_summarize.py`
  - `stage_1` / `stage_2` / `stage_3` 始终输出三键

- `tools/extract_keypoints.py`
  - 按 `BUCKET_ORDER`（pitfalls → concepts → methods → examples）+ 同类内 confidence 降序
  - normalize 去重
  - 最多 `max_points`（默认 12）
  - 支持 `min_confidence` 阈值过滤（避免低置信度挤占）

- `tools/validate_result.py`
  - 未分类比例、空主分类、重复 chunk、阶段总结缺失
  - 消费 `failed_sources` / `empty_sources` 并产出 `failed_sources_present` / `empty_extracted_sources` 警告
  - enrichment 启用时校验 `web_resources` 的 `url/relevance_reason` 缺失
  - 消费语义冲突结果并产出 `semantic_conflicts_detected:<n>` 警告

- `tools/export_notes.py`
  - `result.json` + `result.md`
  - 默认导出“最终整理笔记版” `result.md`（流程诊断保留在 `result.json`）
  - md 完整渲染 Stage 1（theme distribution）+ Stage 2（每类 count+preview）+ Stage 3（四个子列表）
  - `Failed Sources` 列出带 `reason` 的失败项
  - 新增 `Ingestion Summary` 小节（仅在存在 ingestion_summary 时显示）
  - 新增 `Topic Overview` 小节（topic counts + per-source label）
  - 新增 `Semantic Conflicts` 小节（当存在冲突时）
  - 支持 `markdown_use_details`（分类区块可折叠）
  - `review_needed` 与 `pipeline_notes` 分区呈现
  - `failed_sources` / `empty_extracted_sources` 仅在非空时显示

- `tools/export_word.py`
  - 从 `result.md` 生成基础 `result.docx`（可选）
  - `python-docx` 依赖异常时降级，不中断主流程（记录 pipeline_notes）

- `app.py`
  - CLI 串联全流程
  - 自动加载项目根目录 `.env`（不覆盖已有系统环境变量）
  - 输入支持文件 / 目录 / glob；默认跳过项目元目录
  - 目录 glob 模式动态取自 `parse_inputs.SUPPORTED_EXTENSIONS`（docx/png/jpg/jpeg 会被自动拾取）
  - 注入 stdout notifier（`[ingest]` 前缀），可用 `--quiet` 关闭
  - 在 `chunk_notes` 后、`classify_notes` 前新增 `topic_coarse_classify`
  - 新增 CLI 参数：`--topic-mode` / `--topic-taxonomy` / `--topic-api-timeout` / `--topic-api-retries`
  - 新增 web enrichment 参数：`--enable-web-enrichment` / `--web-enrichment-mode` / `--web-enrichment-timeout` / `--web-enrichment-max-items`
  - 新增 keypoint 参数：`--keypoint-min-confidence`
  - 新增：`--keypoint-max-points`、`--config`
  - 运行时配置驱动：chunk 长度、分类字典、OCR 语言、导出折叠
  - 全部输入失败/为空时，`pipeline_notes` 追加 `"no usable input text"`，主流程不崩溃
  - `review_needed` 仅含 chunk 级问题；validation warnings 进 `pipeline_notes`
  - topic 层 warnings 进入 `pipeline_notes`（系统级）
  - web enrichment warnings 与 semantic conflict 摘要进入 `pipeline_notes`
  - 当用户显式选择 API 模式但 URL 未配置时，打印提示：`请接入API后使用`
  - 支持统一 API 环境变量：`KNOWLEDGEHARNESS_API_URL / KNOWLEDGEHARNESS_API_KEY`
  - 支持 `--export-docx`，可选导出 `result.docx`
  - 支持 `--full-report` 切换为完整报告版 md（默认纯笔记版）
  - CLI 结尾打印 `is_valid` 与 warnings 摘要

- `service/api_server.py`
  - 提供最小 FastAPI 服务入口（`/health`、`/pipeline/run`、`/pipeline/capabilities`）
  - 复用 `run_pipeline`，保持与 CLI 一致的降级语义
  - 通过 `requirements-api.txt` 进行可选依赖安装

- `service/simple_ui.py`
  - 提供最简本地 Web 检查界面（stdlib `http.server`，无额外依赖）
  - 支持输入路径、topic/web mode、keypoint 参数并直接触发 `run_pipeline`
  - 支持上传文件、统一 API 设置页、可选 docx 导出
  - 页面聚焦展示最终文档输出（`result.md` 内容）与导出路径

- `tests/test_parse_inputs.py`
  - 仅覆盖"输入扩展与上传告知"模块的核心路径（不含 pytest 依赖，可直接 `python3` 运行）
  - 用例：extension surface / unsupported / empty / file_not_found / docx happy / OCR 缺失降级 / notifier 事件流 / encrypted pdf parse_error / docx heading_path 注入

- `tests/test_topic_coarse_classify.py`
  - local/unknown/out-of-scope fallback/api exception/taxonomy fallback

- `tests/test_stage1_core.py`
  - chunk/classify/validate/export/app 的阶段 1 回归

- `tests/test_phase2_features.py`
  - web enrichment local schema
  - validation 的 web 字段检查（仅 enrichment enabled）
  - semantic conflict 检测
  - topic api retry 行为

- `tests/test_phase3_non_api.py`
  - runtime config merge
  - markdown details export
  - keypoint max_points 上限

- `tests/test_api_service_entry.py`
  - FastAPI 服务入口存在性检查（fastapi 缺失时 skip）

## 3) Not Implemented / Placeholder

- Flask 服务入口未实现（当前仅 FastAPI 最小入口）
- API 接口联调待外部接口规范与鉴权信息就绪
- 全量 pytest 自动化测试套件未建立；当前为 5 份 stdlib-only 测试脚本（可直接 `python3 tests/<name>.py` 运行）：
  `test_parse_inputs.py` / `test_stage1_core.py` / `test_topic_coarse_classify.py` /
  `test_phase2_features.py` / `test_phase3_non_api.py`（合计 70 用例；pypdf 可用时全跑，缺失时最多 SKIP 2 条）
- 图片 OCR 在默认环境下**不真正执行**（需安装 `requirements-ocr.txt` + `tesseract` 系统二进制）；默认行为是结构化降级，而非"已实现完整 OCR"。容器内（`Dockerfile`）默认可用
- Topic API 仅提供可选接入点；默认运行不依赖外部 API
- Web enrichment API 仅提供可选接入点；默认可走 local 模式
- 语义冲突检测当前为启发式规则版，非 NLI 语义推理
- 运行时配置当前为 JSON 文件方案；未接入远程配置中心

## 4) Known Issues

1. 规则分类依赖关键词字典，未在字典覆盖的表述仍会进 `unclassified`。
2. `_leading_label` 只识别"短前缀 + 中/英冒号"，纯口语化段落识别率低。
3. Markdown 导出可读性已显著提升，但未做分级目录折叠，长笔记仍显冗长。
4. 图片 OCR 的语言包（`chi_sim`）需单独安装，否则会回退到 `eng`；混合中英图片在仅 `eng` 的环境下可能漏字。
5. topic 粗分类当前以 alias 命中为主；当领域词库覆盖不足时会降级 `unknown_topic`。
6. web enrichment local 模式只会提取用户资料中已有链接，不会主动联网搜索。
7. encrypted PDF 降级测试依赖 `pypdf` 可用；依赖缺失时测试会 skip。

## 5) Acceptance Gate

- 所有修改必须通过 `docs/ACCEPTANCE.md` 中的 §3 通用 Gate 和对应模块 §4 条目。
- 输入扩展与上传告知模块的验收条目见 `docs/ACCEPTANCE.md` §4 "parse_inputs (Input Expansion)"。
- 硬约束见 `docs/ACCEPTANCE.md` §5 与 `SKILL.md` Prohibitions。

## 6) Truth Alignment Statement

本文件只描述仓库当前真实状态。未实现能力不得写成"已实现"。
若文档与代码冲突：先修正其中一方以恢复一致，再继续开发。
