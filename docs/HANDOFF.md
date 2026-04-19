# HANDOFF

Last Updated: 2026-04-20

## 当前可用交接结论

- MVP 主流程端到端可跑并产出 `result.json` / `result.md`。
- **本轮交付**：输入扩展与上传告知模块（Input Expansion + User Ingestion Notice）
  - txt / md / pdf / **docx** 默认可用（docx 依赖 `python-docx`，已进 `requirements.txt`）
  - **图片 `.png / .jpg / .jpeg` opt-in OCR**：依赖 `requirements-ocr.txt` + 系统 `tesseract` 二进制齐全才激活；缺失任一项时结构化降级为 `reason=ocr_backend_unavailable`，主流程不崩溃
  - 解析阶段注入 `notifier` 事件流（`detected → start → success|failed → summary`）；CLI 默认打印 `[ingest]` 进度，`--quiet` 可关闭
  - `overview.ingestion_summary` 作为运行期真实能力自报表（含 `supported_extensions_effective` / `ocr_backend` / `breakdown_by_type` 等）
  - 失败源统一 schema：`{source, source_name, source_type, reason, error}`；`reason` ∈ `{unsupported_file_type, file_not_found, parse_error, ocr_backend_unavailable}`
  - 全部输入失败 / 空时 `pipeline_notes` 自动追加 `"no usable input text: every detected file failed or was empty"`
  - 新增最小测试 `tests/test_parse_inputs.py`（stdlib-only，不依赖 pytest）
- **验收线**：`samples/demo.md` 仍 `is_valid=True`；本轮交付的 30 条 ACCEPTANCE 点名全绿；`tests/test_parse_inputs.py` 25/25 PASS（`tesseract` 缺失时 27/27，自动 SKIP 1 条不适用用例）。

## 建议的下一步（按顺序）

1. 补齐测试基础设施（对应 `docs/TODO.md` P0）：为 `chunk_notes / classify_notes / validate_result / export_notes` 各建最小 stdlib 测试，与 `tests/test_parse_inputs.py` 并列，保证重构有回归网。
2. 为 `app.py` 增加失败场景回归用例（空输入、仅失败输入、PDF 加密、混合类型）。
3. 接入最小 web enrichment（可开关），严格保留 `title / url / purpose / relevance_reason`；并在 validation 中补"缺失链接"校验（仅在 enrichment 启用时触发）。
4. 引入关键词级冲突检测（最小可用版本），为后续语义冲突铺路。

## 交接注意事项

- 开发前必须先读：`README.md`、`SKILL.md`、`docs/PROJECT_STATE.md`、`docs/ACCEPTANCE.md`。
- 文档权威顺序见 `docs/ACCEPTANCE.md` §1；冲突时 `docs/PROJECT_STATE.md` 为事实基线。
- 不要把占位能力写成已实现；**图片 OCR 必须保留 opt-in + 降级语义**，不能被改成"默认可用"描述。
- `review_needed` 只承载 chunk 级问题；validation / 系统级警告必须走 `pipeline_notes`。
- `samples/demo.md` 的 `validation.is_valid == True` 是硬验收线，变红时必须先修到绿再合入。
- 任何新扩展（联网、冲突检测、OCR 再升级、API）需先在 `docs/TODO.md` 登记 → 完成后按 `docs/ACCEPTANCE.md` §2 的 4 步流程同步所有文档 → 验收过 G0–G3 + 对应模块 §4 条目 → 才能标 `[x]`。

## 本轮交付对依赖栈的影响

| 依赖 | 是否写入 requirements | 安装位置 |
|------|---------------------|---------|
| `pypdf>=4.2.0` | `requirements.txt`（旧） | pip |
| `python-docx>=1.1.0` | `requirements.txt`（新） | pip |
| `pytesseract>=0.3.10` | `requirements-ocr.txt`（新，opt-in） | pip |
| `Pillow>=10.0.0` | `requirements-ocr.txt`（新，opt-in） | pip |
| `tesseract-ocr` 系统二进制 | **不在 pip 管理**，用户自行 `apt-get install tesseract-ocr`（加上 `tesseract-ocr-chi-sim` 获得中文支持） | OS package manager |
