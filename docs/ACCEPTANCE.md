# ACCEPTANCE CRITERIA

本文件是 KnowledgeHarness 在 Harness Engineering 框架下的"验收层"。
任何由 Codex/Agent 完成的开发任务，在宣告完成前，必须按此清单自检。
任何与本文件冲突的输出都不视为完成。

## 1. Harness Engineering 分层（框架建立）

| 层级 | 文件 | 性质 | 作用 |
|------|------|------|------|
| Agent Skill | `SKILL.md` | 规范 | 约束 Agent 行为：先分类后总结、用户资料优先、不编造、不静默丢弃、失败降级 |
| Architecture | `docs/ARCHITECTURE.md` | 参考 | 模块划分与主流程图 |
| State | `docs/PROJECT_STATE.md` | 权威 | 仓库实时真实状态（已实现 / 未实现 / 已知问题） |
| Session Rules | `.codex/session_rules.md` | 规范 | 会话级前置门禁：改前必读 + 变更范围声明 |
| Acceptance | `docs/ACCEPTANCE.md` | 规范 | 模块级与任务级验收条件（本文件） |
| Handoff | `docs/HANDOFF.md` | 参考 | 当前版本的交接结论 |
| TODO | `docs/TODO.md` | 运行 | 已登记但未完成的优先级列表 |
| Memory | `project_memory/` | 历史 | 对话上下文副本，非权威；冲突以 State 为准 |

权威顺序（冲突时从上往下覆盖）：
1. `docs/PROJECT_STATE.md`（事实）
2. `SKILL.md` / `docs/ACCEPTANCE.md`（规则）
3. `docs/ARCHITECTURE.md` / `README.md`（说明）
4. `project_memory/*`（历史）

## 2. 边界划分（什么在 MVP 里、什么不在）

### 在 MVP 范围内
- txt / md / pdf / **docx** 解析
- 图片（`.png / .jpg / .jpeg`）**opt-in OCR**：依赖 `requirements-ocr.txt` + `tesseract` 系统二进制齐全时才真正 OCR；否则降级为 `ocr_backend_unavailable`
- 输入阶段的结构化告知（notifier 事件 + `overview.ingestion_summary`）
- 基于规则（关键词 + 起始标签）的分类
- 三阶段总结
- 基于置信度与类别优先级的 key points 提炼
- 规则化校验：未分类比例、空主分类、重复 chunk、阶段总结缺失、失败/空文件追踪
- JSON + Markdown 双路导出

### 明确不在 MVP 范围内（占位或未来工作）
- Web enrichment（`web_resources` 当前始终为 `[]`）
- 语义级冲突检测（当前仅重复检测）
- HTTP 服务层（FastAPI / Flask）
- 全量 pytest 自动化测试套件（当前仅 `tests/test_parse_inputs.py` 最小测试）
- 图片 OCR 的"无依赖默认可用"路径（设计上就选择了 opt-in，不拟改变）

Codex 改动时，如把上面任一项从"未实现"迁移到"已实现"，必须：
1. 在 `docs/PROJECT_STATE.md` 的 "Implemented Modules" 新增一项；
2. 从 `docs/PROJECT_STATE.md` 的 "Not Implemented / Placeholder" 删除对应项；
3. 在 `docs/ACCEPTANCE.md` §4 补本模块的验收条目；
4. 在 `docs/TODO.md` 将对应条目划掉或迁移。

## 3. 通用 Gate（每次 PR 必过）

### G0 · 阅读门禁
- [ ] 已读 `README.md` / `SKILL.md` / `docs/PROJECT_STATE.md` / `docs/ACCEPTANCE.md`
- [ ] 已输出"本次变更范围声明"（哪些文件会动、哪些范围绝不碰）
- [ ] 若发现文档与代码不一致，已先修正再继续

### G1 · 管道完整性
- [ ] `python3 app.py samples/demo.md --output-dir outputs` 能端到端跑通
- [ ] `validation.is_valid == True`（除非本次任务是有意引入负样本测试）
- [ ] `result.json` 顶层键至少包含：
      `overview` / `source_documents` / `categorized_notes` / `stage_summaries` /
      `key_points` / `web_resources` / `review_needed` / `pipeline_notes` / `validation`

### G2 · 来源可追溯
- [ ] 每个 chunk 保留 `chunk_id` / `source_name` / `source_type` / `source_path` / `raw_text` / `extracted_text`
- [ ] 每条 web_resource（若启用）保留 `title` / `url` / `purpose` / `relevance_reason`

### G3 · 真实性守则
- [ ] 未实现能力没有被描述为"已实现"
- [ ] `docs/PROJECT_STATE.md` 已同步本次变更（新增能力进 Implemented，退役能力从 Placeholder 删除）
- [ ] `docs/TODO.md` 里已完成项已被勾掉，未完成项保留
- [ ] 没有使用 `chunk_id = "SYSTEM"` 之类的伪 chunk 绕过 review_needed 语义

## 4. 模块级验收

### parse_inputs (Input Expansion + User Ingestion Notice)
- [ ] 支持扩展集 = `{.txt, .md, .pdf, .docx, .png, .jpg, .jpeg}`；SUPPORTED_EXTENSIONS 是这个集合的权威来源
- [ ] txt / md / pdf / docx 在依赖齐全时必须"完整可用"（提取非空文本）
- [ ] 图片扩展采用 **opt-in OCR**：探测 `pytesseract` + `PIL` + `tesseract` 二进制三项齐全才真 OCR；任一缺失则 `reason=ocr_backend_unavailable`（**不得伪装成功**）
- [ ] 解析失败的文件进入 `logs.failed_sources`，每条带 `reason` ∈
      `{unsupported_file_type, file_not_found, parse_error, ocr_backend_unavailable}`，不中断主流程
- [ ] 解析成功但文本为空的文件进入 `logs.empty_extracted_sources`
- [ ] 每个成功文档保留 `source_name` / `source_type` / `source_path` / `raw_text` / `extracted_text`
- [ ] 可选 `notifier(event, payload)` 回调至少触发：`detected → start(每文件) → success|failed(每文件) → summary`
- [ ] 返回体包含 `ingestion_summary`，字段：`detected / supported / unsupported / succeeded / empty_extracted / failed / breakdown_by_type / supported_extensions_effective / image_extensions_opt_in / ocr_backend`
- [ ] 文档必须如实声明 OCR 是 opt-in：安装路径与降级语义都在 `README.md` / `docs/PROJECT_STATE.md` 中可查
- [ ] `tests/test_parse_inputs.py` 至少覆盖：extension surface / unsupported / empty / file_not_found / docx happy / OCR 缺失降级 / notifier 事件流，可直接 `python3 tests/test_parse_inputs.py` 运行

### chunk_notes
- [ ] 按段落切分，长段按句切分
- [ ] 单句仍超 `max_chars` 时必须按字符硬切（无静默超长）
- [ ] 生成的 chunk 继承来源元数据并带稳定 `chunk_id`

### classify_notes
- [ ] 输出标签仅来自 `CATEGORIES`
- [ ] tie-break 必须走 `CATEGORY_PRIORITY`，不允许在 tie 时一律落回 `unclassified`
- [ ] `confidence < 0.4` 的 chunk 必须同时出现在 `review_needed`
- [ ] 0 关键词命中的 chunk 进入 `unclassified` + `review_needed`，原因记录为 "no keyword matched"

### stage_summarize
- [ ] 总是输出 `stage_1` / `stage_2` / `stage_3` 三个键
- [ ] 输入为空时可降级为空结构（count=0 / preview=[]），不抛异常

### extract_keypoints
- [ ] 候选集按 `BUCKET_ORDER` 顺序 + 同类内 `confidence` 降序组织
- [ ] 通过 normalize 后对比去重
- [ ] 最终数量 ≤ `max_points`（默认 12）

### validate_result
- [ ] 必须检查：未分类比例（>35% 告警）、空主分类、重复 chunk、阶段总结缺失
- [ ] 必须消费 `failed_sources` 与 `empty_sources`，并在它们非空时产生对应 warning
- [ ] `is_valid` 当且仅当 `warnings == []` 时为 True

### export_notes
- [ ] 同时生成 `result.json` 和 `result.md`
- [ ] md 必须完整渲染 Stage 1（theme distribution）、Stage 2（每类 count + preview）、Stage 3（4 个子列表）
- [ ] md 中 `Review Needed` 与 `Pipeline Notes` 作为独立小节分别呈现
- [ ] md 中 Failed Sources / Empty Extracted Sources 仅在非空时出现

### app.py
- [ ] `collect_input_files` 默认跳过项目元目录（`outputs/ docs/ project_memory/ .codex/ .git/ __pycache__/ .venv/`）
- [ ] 目录 glob 模式由 `parse_inputs.SUPPORTED_EXTENSIONS` 驱动，不再硬编码
- [ ] 注入 stdout notifier（`[ingest]` 前缀），支持 `--quiet` 关闭
- [ ] `review_needed` 只承载 chunk 级问题；validation warnings 必须进入 `pipeline_notes`
- [ ] 全部输入失败/空时，`pipeline_notes` 必须追加 `"no usable input text: ..."`，主流程不崩溃
- [ ] `overview` 内包含 `failed_sources` / `empty_extracted_sources` / `ingestion_summary`
- [ ] CLI 结尾打印 `is_valid` 与 warnings 摘要

## 5. 硬约束（禁止事项）

- 禁止把占位功能（web enrichment、conflict detection、API、pytest 全量套件）描述为已实现
- **禁止把图片 OCR 描述为"无依赖默认可用"；必须如实标注 opt-in 与降级语义**
- 禁止以对话中的历史记忆替代 `docs/PROJECT_STATE.md` 作为事实依据
- 禁止在 `samples/demo.md` 上让 `validation.is_valid == False` 却不解释原因
- 禁止在 web_resources 条目中遗漏 `url` 或 `relevance_reason`（当 enrichment 启用时）
- 禁止把系统级警告塞进 `review_needed`（违反 G3 中"不得使用伪 chunk_id=SYSTEM"规则）
- 禁止跳过 validation 或 validation 失败仍继续导出而不产生 pipeline_notes
- 禁止让单个文件的解析失败中断整个 pipeline（`parse_inputs` 的任何新分支都必须走"降级 + 显式记录"）
