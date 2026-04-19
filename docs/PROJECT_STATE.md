# PROJECT_STATE

Last Updated: 2026-04-20

## 1) Current Project Structure

```text
KnowledgeHarness/
├── .codex/
│   └── session_rules.md
├── .gitignore
├── README.md
├── SKILL.md
├── app.py
├── requirements.txt
├── requirements-ocr.txt             # opt-in OCR backend
├── docs/
│   ├── ACCEPTANCE.md
│   ├── ARCHITECTURE.md
│   ├── HANDOFF.md
│   ├── PROJECT_STATE.md
│   └── TODO.md
├── tools/
│   ├── __init__.py
│   ├── parse_inputs.py
│   ├── chunk_notes.py
│   ├── classify_notes.py
│   ├── stage_summarize.py
│   ├── extract_keypoints.py
│   ├── validate_result.py
│   └── export_notes.py
├── tests/
│   ├── __init__.py
│   └── test_parse_inputs.py         # stdlib-only; runs via `python3 tests/...`
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
  - **图片 `.png` / `.jpg` / `.jpeg`：opt-in OCR**，探测 `pytesseract` + `Pillow` + `tesseract` 二进制三者齐全才走真 OCR；任一缺失则 `failed_sources[*].reason = "ocr_backend_unavailable"`（不伪装成功）
  - 失败源统一 schema：`{source, source_name, source_type, reason, error}`；`reason` 取值 `unsupported_file_type / file_not_found / parse_error / ocr_backend_unavailable`
  - 可选 `notifier(event, payload)` 回调：事件 `detected / start / success / failed / summary`
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

- `tools/stage_summarize.py`
  - `stage_1` / `stage_2` / `stage_3` 始终输出三键

- `tools/extract_keypoints.py`
  - 按 `BUCKET_ORDER`（pitfalls → concepts → methods → examples）+ 同类内 confidence 降序
  - normalize 去重
  - 最多 `max_points`（默认 12）

- `tools/validate_result.py`
  - 未分类比例、空主分类、重复 chunk、阶段总结缺失
  - 消费 `failed_sources` / `empty_sources` 并产出 `failed_sources_present` / `empty_extracted_sources` 警告

- `tools/export_notes.py`
  - `result.json` + `result.md`
  - md 完整渲染 Stage 1（theme distribution）+ Stage 2（每类 count+preview）+ Stage 3（四个子列表）
  - `Failed Sources` 列出带 `reason` 的失败项
  - 新增 `Ingestion Summary` 小节（仅在存在 ingestion_summary 时显示）
  - `review_needed` 与 `pipeline_notes` 分区呈现
  - `failed_sources` / `empty_extracted_sources` 仅在非空时显示

- `app.py`
  - CLI 串联全流程
  - 输入支持文件 / 目录 / glob；默认跳过项目元目录
  - 目录 glob 模式动态取自 `parse_inputs.SUPPORTED_EXTENSIONS`（docx/png/jpg/jpeg 会被自动拾取）
  - 注入 stdout notifier（`[ingest]` 前缀），可用 `--quiet` 关闭
  - 全部输入失败/为空时，`pipeline_notes` 追加 `"no usable input text"`，主流程不崩溃
  - `review_needed` 仅含 chunk 级问题；validation warnings 进 `pipeline_notes`
  - CLI 结尾打印 `is_valid` 与 warnings 摘要

- `tests/test_parse_inputs.py`
  - 仅覆盖"输入扩展与上传告知"模块的核心路径（不含 pytest 依赖，可直接 `python3` 运行）
  - 用例：extension surface / unsupported / empty / file_not_found / docx happy / OCR 缺失降级 / notifier 事件流

## 3) Not Implemented / Placeholder

- Web enrichment 未接入（`web_resources` 固定返回 `[]`）
- 语义冲突检测未实现（当前仅 `validate_result` 做重复检测）
- HTTP API 服务层（FastAPI / Flask）未实现
- 全量 pytest 自动化测试套件未建立（当前仅本模块最小测试）
- 图片 OCR 在默认环境下**不真正执行**（需安装 `requirements-ocr.txt` + `tesseract` 系统二进制）；默认行为是结构化降级，而非"已实现完整 OCR"

## 4) Known Issues

1. 规则分类依赖关键词字典，未在字典覆盖的表述仍会进 `unclassified`。
2. `_leading_label` 只识别"短前缀 + 中/英冒号"，纯口语化段落识别率低。
3. Markdown 导出可读性已显著提升，但未做分级目录折叠，长笔记仍显冗长。
4. 图片 OCR 的语言包（`chi_sim`）需单独安装，否则会回退到 `eng`；混合中英图片在仅 `eng` 的环境下可能漏字。

## 5) Acceptance Gate

- 所有修改必须通过 `docs/ACCEPTANCE.md` 中的 §3 通用 Gate 和对应模块 §4 条目。
- 输入扩展与上传告知模块的验收条目见 `docs/ACCEPTANCE.md` §4 "parse_inputs (Input Expansion)"。
- 硬约束见 `docs/ACCEPTANCE.md` §5 与 `SKILL.md` Prohibitions。

## 6) Truth Alignment Statement

本文件只描述仓库当前真实状态。未实现能力不得写成"已实现"。
若文档与代码冲突：先修正其中一方以恢复一致，再继续开发。
