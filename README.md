# KnowledgeHarness

KnowledgeHarness 是一个面向学习资料整理的工程化流水线工具，目标是把分散资料转换为可复习的结构化笔记。

## 项目定位

- 用户资料优先（本地输入是主数据源）
- 流程化处理，不走一次性"聊天式总结"
- 输出带来源信息、带校验结果
- 当前实现为 **CLI MVP**，优先验证流程闭环

## 治理文档（Harness Engineering 视角）

| 文件 | 作用 |
|------|------|
| `SKILL.md` | Agent 行为规范（先分类后总结、不编造、占位能力的如实描述） |
| `docs/PROJECT_STATE.md` | 仓库真实状态（已实现 / 未实现 / 已知问题） |
| `docs/ARCHITECTURE.md` | 模块与数据契约 |
| `docs/ACCEPTANCE.md` | 模块级与通用 Gate 的验收条件 |
| `docs/HANDOFF.md` | 当前版本交接结论 |
| `docs/TODO.md` | 已登记未完成事项 |
| `.codex/session_rules.md` | 会话级前置门禁 |
| `project_memory/` | 历史对话副本，非权威 |

## 当前支持能力（已实现）

1. 输入解析
   - 默认支持：`.txt` / `.md` / `.pdf` / `.docx`（`python-docx`）
   - **Opt-in OCR**：`.png` / `.jpg` / `.jpeg` 需额外安装 `requirements-ocr.txt` 与 `tesseract` 系统二进制；未安装时不伪装成功，而是记录 `failed_sources[*].reason == "ocr_backend_unavailable"`
   - 解析失败源 → `logs.failed_sources`（带 `reason`：`unsupported_file_type` / `file_not_found` / `parse_error` / `ocr_backend_unavailable`）
   - 解析成功但正文空 → `logs.empty_extracted_sources`
   - `overview.ingestion_summary`：运行期自报"本次真实可用扩展集 + OCR 后端状态"
2. 文本切分：按段落 → 句子 → 字符三级 fallback，保证不超 `max_chars`
3. 规则分类（关键词 + 起始标签双路打分，tie-break 走 `CATEGORY_PRIORITY`）：
   - `basic_concepts`
   - `methods_and_processes`
   - `examples_and_applications`
   - `difficult_or_error_prone_points`
   - `extended_reading`
   - `unclassified`
4. 三阶段总结：`stage_1 / stage_2 / stage_3`
5. 重点提炼：按类别优先级 + 置信度降序聚合并去重
6. 结果校验：未分类比例、空主分类、重复内容、阶段总结缺失、failed/empty 源提示
7. 导出：`outputs/result.json` + `outputs/result.md`（Stage 1/2/3 完整渲染 + Ingestion Summary）

## 当前未实现或占位（必须知晓）

- Web enrichment 仍是占位：`web_resources = []`，**未接入搜索工具**
- 语义冲突检测未实现（仅做重复检测）
- **图片 OCR 是 opt-in**：默认环境下图片输入会优雅降级为 `ocr_backend_unavailable`；仅在安装 `requirements-ocr.txt` 并具备 `tesseract` 二进制时才真正 OCR
- API 服务（Flask / FastAPI）未实现
- 自动化测试：仅针对"输入扩展与上传告知"模块补了最小 stdlib 测试（`tests/test_parse_inputs.py`），尚未建立 pytest 套件

## 运行方式

1. 安装依赖（核心）：

```bash
pip install -r requirements.txt
```

2.（可选）启用图片 OCR：

```bash
pip install -r requirements-ocr.txt
# 系统层（Debian/Ubuntu）
sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
```

3. 执行（单文件 / 目录 / 通配符均可；项目元目录会被自动跳过）：

```bash
python3 app.py samples/demo.md --output-dir outputs
# 多类型混合输入
python3 app.py samples/ --output-dir outputs
# 静默（不输出 [ingest] 进度）
python3 app.py samples/ --output-dir outputs --quiet
```

4. 查看结果：

- `outputs/result.json`
- `outputs/result.md`

5. 运行本模块的最小测试（不依赖 pytest）：

```bash
python3 tests/test_parse_inputs.py
```

## 输出结构契约

- `overview`：`source_count` / `chunk_count` / `failed_sources` / `empty_extracted_sources` / `ingestion_summary`
- `source_documents`
- `categorized_notes` / `stage_summaries` / `key_points`
- `web_resources`（占位）
- `review_needed`（仅 chunk 级问题）
- `pipeline_notes`（系统级警告，如 validation warnings、"no usable input text"）
- `validation`（`is_valid` + `warnings` + `stats`）

## MVP 边界

- 先保证流程清晰、模块可独立测试
- 不追求模型能力或复杂 UI
- 不把占位能力描述成已上线能力
- 任何扩展（联网、OCR、API）需在 `docs/TODO.md` 明确列入并按 `docs/ACCEPTANCE.md` 验收后再标记"已完成"
