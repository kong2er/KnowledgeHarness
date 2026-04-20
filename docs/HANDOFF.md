# HANDOFF

Last Updated: 2026-04-20

## 当前可用交接结论

- MVP 主流程端到端可跑并产出 `result.json` / `result.md`。
- **本轮交付**（两次叠加，均在本次会话落地）：
  1. **输入扩展与上传告知模块**（`feat/input-expansion`）：txt/md/pdf/docx 默认可用，图片 opt-in OCR + 显式降级。
  2. **Topic Coarse Classification Layer**（今天主任务）：document 级粗分类，受本地 `config/topic_taxonomy.json` 约束，支持 `auto/local/api` 三模式，API 越界/失败降级为 local 或 `unknown_topic`；结果挂在 `result.topic_classification`。
  3. **Phase-2 配套 P1 层**：
     - `web_enrichment`（开关可控，`off/local/api/auto`；严格输出 `title/url/purpose/relevance_reason`）
     - `detect_semantic_conflicts`（启发式关键词互斥，非 NLI 语义推理）
     - `validate_result` 消费两者并产生 `web_resources_missing_url/relevance_reason` / `semantic_conflicts_detected:<n>` 告警
  4. **Phase-3 运行时与交付增强**：
     - `runtime_config`：`config/pipeline_config.json` 深度合并默认值，失败降级
     - `--config` / `--topic-mode` / `--topic-taxonomy` / `--enable-web-enrichment` / `--keypoint-min-confidence` / `--keypoint-max-points` 等 CLI 旋钮
     - Markdown 折叠导出（`markdown_use_details`）
     - `Dockerfile` + `.dockerignore`：容器内默认装好 `tesseract-ocr` + `tesseract-ocr-chi-sim`，让 OCR 从 opt-in 变"开箱即用"
  5. **测试网扩面**：`tests/test_stage1_core.py`、`tests/test_phase2_features.py`、`tests/test_phase3_non_api.py`、`tests/test_topic_coarse_classify.py` 叠加到原先的 `tests/test_parse_inputs.py`，合计 **70 用例全 PASS**（pypdf 可用时，原本 2 条 SKIP 不再出现）。

- **本会话期间修正项**（在代码审计后发现的真实问题，这一次会话里已修）：
  1. `config/topic_taxonomy.json` 中 `software_engineering` 别名 `"测试"` 过宽，会把 ML 文档中的"测试集"误匹配成 SE。已移除孤立 `"测试"`、扩充更明确的 SE 测试词（`unit test` / `集成测试` / `代码评审` / `重构` 等），并新增 `machine_learning` 标签。`samples/demo.md` 现在会正确分到 `machine_learning`（conf 0.9）。
  2. `docs/PROJECT_STATE.md` §3 与 `docs/ACCEPTANCE.md` §2 关于"当前仅 `tests/test_parse_inputs.py`"的陈述已过期（实为 5 份测试文件），本轮已同步修正。

- **硬验收线**：
  - `python3 app.py samples/demo.md --output-dir outputs` → `is_valid=True` / warnings=[]
  - `python3 app.py samples/ --output-dir outputs`（docx + md + png 混合；若 tesseract 在位则 png 真 OCR） → `is_valid=True`
  - 5 份测试脚本合计 `70 passed, 0 failed`（pypdf 缺失时最多 SKIP 2 条编码 PDF 用例，主流程不受影响）

## 建议的下一步（按顺序）

1. **合并上述变更并打 tag**：本次会话把 codex 未提交的成果 + 本人修复合并为一个 commit 推到 `origin/main`。
2. **topic taxonomy 真实语料演练**：在你自己的真实资料目录上跑一次 `python3 app.py <your_dir> --topic-mode local`，看 `topic_classification.topic_groups` 是否合理；若主题漂移，进一步扩 `config/topic_taxonomy.json` 的 aliases。
3. **接入 Topic API**（仅当你准备好一个私有可用的 `TOPIC_CLASSIFIER_API_URL`）：代码与 prompt 约束框架已完整，只要服务端按 `allowed_labels` 约束返回即可；否则保持 `local`/`auto` 默认态。
4. **引入二次整理层**（按领域聚合 → 大类内部笔记生成）：在 topic 层基础上做"粗分类完成 → 每个 topic 下生成子笔记"。这是粗分类为后续准备的下一站，但**不是今天的事**。
5. **NLI / 向量式语义冲突检测**：当前是关键词互斥启发式，后续可替换为语义推理层，但仍保持"启发式作为快速路径 + 语义模型作为深度路径"的分层。

## 交接注意事项

- 开发前必须先读：`README.md`、`SKILL.md`、`docs/PROJECT_STATE.md`、`docs/ACCEPTANCE.md`。
- 文档权威顺序见 `docs/ACCEPTANCE.md` §1；冲突时 `docs/PROJECT_STATE.md` 为事实基线。
- 不要把占位能力写成已实现；**图片 OCR 必须保留 opt-in + 降级语义**，不能被改成"默认可用"描述；**Topic API 仅为可选协助**，本地约束标签集合是唯一权威。
- `review_needed` 只承载 chunk 级问题；validation / 系统级警告 / topic 层 warnings / web enrichment warnings / 冲突摘要都必须走 `pipeline_notes`。
- `samples/demo.md` 的 `validation.is_valid == True` 是硬验收线，变红时必须先修到绿再合入。
- 任何新扩展需先在 `docs/TODO.md` 登记 → 完成后按 `docs/ACCEPTANCE.md` §2 的 4 步流程同步所有文档 → 验收过 G0–G3 + 对应模块 §4 条目 → 才能标 `[x]`。

## 本轮交付对依赖栈的影响

| 依赖 | 是否写入 requirements | 安装位置 |
|------|---------------------|---------|
| `pypdf>=4.2.0` | `requirements.txt` | pip |
| `python-docx>=1.1.0` | `requirements.txt` | pip |
| `pytesseract>=0.3.10` | `requirements-ocr.txt`（opt-in） | pip |
| `Pillow>=10.0.0` | `requirements-ocr.txt`（opt-in） | pip |
| `tesseract-ocr` / `tesseract-ocr-chi-sim` 系统二进制 | **不在 pip 管理**，用户自行 `apt-get install`（或直接用 `Dockerfile`） | OS package manager 或容器 |
| 无新增 Python 依赖 | Topic / Web enrichment / Conflict detection 全部用标准库 (`urllib` / `re` / `json`)，不引入 OpenAI / vector-db 等重量级栈 | — |
