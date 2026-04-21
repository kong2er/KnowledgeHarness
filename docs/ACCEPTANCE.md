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
- 主题粗分类层（document 级，标签受本地 taxonomy 约束；API 仅可选协助）
- 可开关 Web enrichment（off/local/api/auto）
- 启发式语义冲突检测（关键词互斥规则）
- 基于规则（关键词 + 起始标签）的分类
- 三阶段总结
- 基于置信度与类别优先级的 key points 提炼
- 规则化校验：未分类比例、空主分类、重复 chunk、阶段总结缺失、失败/空文件追踪
- JSON + Markdown 双路导出；支持"最终笔记版"与"完整报告版"切换
- Word (.docx) 导出（基于 `_render_final_notes_markdown` 输出子集）
- 运行时配置（JSON）与可选折叠导出
- **本地 Web UI**（`service/simple_ui.py`）：stdlib-only，含文件池、上传限额、输出目录透明化、masked API key、路径遍历防护
- **最小 FastAPI 服务入口**（`service/api_server.py`）
- **最小 Flask 服务入口**（`service/flask_server.py`）

### 明确不在 MVP 范围内（占位或未来工作）
- 高级（NLI/向量）语义冲突检测
- 生产级 HTTP 服务层（鉴权、限流、任务队列、审计）
- 全量 pytest 自动化测试套件（当前为 7 份 stdlib-only 测试脚本：`tests/test_parse_inputs.py` / `test_stage1_core.py` / `test_topic_coarse_classify.py` / `test_phase2_features.py` / `test_phase3_non_api.py` / `test_api_service_entry.py` / `test_flask_service_entry.py`，合计 74 条用例 + 1 条可选 FastAPI 入口断言）
- `service/simple_ui.py` 的 HTTP 层自动化断言（目前仅手工 curl 验证）
- 图片 OCR 的"无依赖默认可用"路径（设计上就选择了 opt-in，不拟改变；容器镜像 `Dockerfile` 视为"开箱即用"的交付形态）

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
      `overview` / `source_documents` / `topic_classification` / `categorized_notes` / `stage_summaries` /
      `key_points` / `web_resources` / `semantic_conflicts` / `review_needed` / `pipeline_notes` / `validation`

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
- [ ] docx 需支持 heading 样式层级注入（`heading_path`）以服务后续分类
- [ ] 图片扩展采用 **opt-in OCR**：探测 `pytesseract` + `PIL` + `tesseract` 二进制三项齐全才真 OCR；任一缺失则 `reason=ocr_backend_unavailable`（**不得伪装成功**）
- [ ] 解析失败的文件进入 `logs.failed_sources`，每条带 `reason` ∈
      `{unsupported_file_type, file_not_found, parse_error, ocr_backend_unavailable}`，不中断主流程
- [ ] 解析成功但文本为空的文件进入 `logs.empty_extracted_sources`
- [ ] 每个成功文档保留 `source_name` / `source_type` / `source_path` / `raw_text` / `extracted_text`
- [ ] 可选 `notifier(event, payload)` 回调至少触发：`detected → start(每文件) → success|failed(每文件) → summary`
- [ ] 返回体包含 `ingestion_summary`，字段：`detected / supported / unsupported / succeeded / empty_extracted / failed / breakdown_by_type / supported_extensions_effective / image_extensions_opt_in / ocr_backend`
- [ ] 文档必须如实声明 OCR 是 opt-in：安装路径与降级语义都在 `README.md` / `docs/PROJECT_STATE.md` 中可查
- [ ] `tests/test_parse_inputs.py` 至少覆盖：extension surface / unsupported / empty / file_not_found / docx happy / OCR 缺失降级 / notifier 事件流，可直接 `python3 tests/test_parse_inputs.py` 运行
- [ ] `tests/test_parse_inputs.py` 覆盖 encrypted pdf 失败降级（依赖可用时）与 docx heading_path 注入

### chunk_notes
- [ ] 按段落切分，长段按句切分
- [ ] 单句仍超 `max_chars` 时必须按字符硬切（无静默超长）
- [ ] 生成的 chunk 继承来源元数据并带稳定 `chunk_id`

### classify_notes
- [ ] 输出标签仅来自 `CATEGORIES`
- [ ] tie-break 必须走 `CATEGORY_PRIORITY`，不允许在 tie 时一律落回 `unclassified`
- [ ] `confidence < 0.4` 的 chunk 必须同时出现在 `review_needed`
- [ ] 0 关键词命中的 chunk 进入 `unclassified` + `review_needed`，原因记录为 "no keyword matched"

### topic_coarse_classify
- [ ] 输入粒度为 document/source（不是 chunk）
- [ ] 输出标签仅来自本地 taxonomy 的 `allowed_labels`
- [ ] 必须始终包含 `unknown_topic` 作为合法降级标签
- [ ] `mode=api/auto` 时，API 输出越界标签必须被拒绝并降级（local 或 unknown）
- [ ] API 不可用/超时/解析失败不得中断主流程，必须有 `warnings`
- [ ] 结果包含每个 source 的 `topic_label/confidence/reason/used_api/api_attempts/fallback_state`

### web_enrichment
- [ ] 支持 `enabled + mode(off/local/api/auto)` 开关组合
- [ ] 输出条目必须包含 `title/url/purpose/relevance_reason`
- [ ] `local` 模式可从用户资料提取 URL 生成补充条目
- [ ] `api/auto` 失败必须降级且不中断主流程

### detect_semantic_conflicts
- [ ] 对互斥声明关键词给出冲突对（chunk_a/chunk_b + reason）
- [ ] 无冲突时输出空列表，不抛异常

### stage_summarize
- [ ] 总是输出 `stage_1` / `stage_2` / `stage_3` 三个键
- [ ] 输入为空时可降级为空结构（count=0 / preview=[]），不抛异常

### extract_keypoints
- [ ] 候选集按 `BUCKET_ORDER` 顺序 + 同类内 `confidence` 降序组织
- [ ] 通过 normalize 后对比去重
- [ ] 最终数量 ≤ `max_points`（默认 12）
- [ ] 支持可选 `min_confidence` 阈值，低于阈值的候选不应进入 key_points

### validate_result
- [ ] 必须检查：未分类比例（>35% 告警）、空主分类、重复 chunk、阶段总结缺失
- [ ] 必须消费 `failed_sources` 与 `empty_sources`，并在它们非空时产生对应 warning
- [ ] web enrichment 启用时，必须检查 `web_resources` 的 `url/relevance_reason` 缺失
- [ ] 必须消费 `semantic_conflicts` 并在非空时告警
- [ ] `is_valid` 当且仅当 `warnings == []` 时为 True

### export_notes
- [ ] 同时生成 `result.json` 和 `result.md`
- [ ] 默认 `final_notes_only=True` 渲染"最终笔记版"：
      必须去掉开头的 category 冠词（"概念：/方法步骤：..."）和尾巴
      `[heading_path: …]`；多源时自动在顶部插 `> 本笔记由 N 份文档合并整理`
      引用行 + 每条笔记带 `*（来源：xxx）*` 斜体标注；总条数 ≤ 12 时
      不得输出"重点速记"节（避免重复）
- [ ] `final_notes_only=False` 时渲染"完整报告版"：Stage 1 theme distribution +
      Stage 2 每类 count+preview + Stage 3 四个子列表，含 Ingestion
      Summary / Topic Overview / Semantic Conflicts / Failed Sources
- [ ] md 中 `Review Needed` 与 `Pipeline Notes` 作为独立小节分别呈现
- [ ] md 中 Failed Sources / Empty Extracted Sources 仅在非空时出现
- [ ] `markdown_use_details=true` 时，分类区块支持 `<details>` 折叠渲染

### export_word
- [ ] 接收 `_render_final_notes_markdown` 已生成的 `result.md`，产出
      `result.docx`（`python-docx` 依赖已在 `requirements.txt`）
- [ ] ATX 标题 `# / ## / ###` → Word Heading 1/2/3 样式
- [ ] Bullet 行 `- ` → Word List Bullet 样式
- [ ] 引用行 `> ` → Word Quote 样式（模板缺失时 fallback 到 Normal）
- [ ] 水平线 `---` / `***` / `___` → 空段落（不渲染字面量字符串）
- [ ] 行内 `*…*` → 真 italic run（`run.italic = True`），不得保留字面量星号
- [ ] 失败时**不得中断主流程**；`app.run_pipeline` 会把异常记进 `pipeline_notes`

### service/api_server.py
- [ ] 提供 `GET /health` 用于服务健康与 API 配置状态探针
- [ ] 提供 `POST /pipeline/run` 并复用 `run_pipeline`（不得分叉核心逻辑）
- [ ] 输入无有效文件时返回 4xx（不允许静默成功）
- [ ] 服务层不得篡改降级语义（topic/web enrichment 失败仍需可降级）
- [ ] 服务依赖为可选安装（`requirements-api.txt`），不应破坏 CLI 默认运行

### service/flask_server.py
- [ ] 提供 `GET /health` 用于服务健康与 API 配置状态探针
- [ ] 提供 `POST /pipeline/run` 并复用 `run_pipeline`（不得分叉核心逻辑）
- [ ] 提供 `GET /pipeline/capabilities`，并标记 `framework = "flask"`
- [ ] 输入无有效文件时返回 4xx（不允许静默成功）
- [ ] 服务层不得篡改降级语义（topic/web enrichment 失败仍需可降级）
- [ ] 服务依赖为可选安装（`requirements-flask.txt`），不应破坏 CLI 默认运行

### service/simple_ui.py
- [ ] **不得** `import cgi`（`cgi` 在 Python 3.13 已移除）；多部分解析使用内置 `_parse_multipart`
- [ ] `/settings` 页面**不得**把任何 API 密钥值回渲染进 HTML `value=` 属性；状态使用 `_mask_value` 显示"已配置（末 4 位：…）"
- [ ] `/settings` 输入框必须是 `type="password"` + `autocomplete="new-password"`；留空提交 = 保持原值（`_write_env_pairs` 丢弃空 update）
- [ ] `/settings` 必须支持"字段级显式清空"（内联 clear 图标或等效控件）；清空动作需映射到 `KEY__clear` 并最终写入 `.env` 的 `KEY=` 语义
- [ ] `/settings` 危险操作（覆盖档案/删除档案/清空环境）必须与普通保存操作隔离，并具备明确确认提示（例如 `confirm`）
- [ ] `/download?name=<basename>` 必须：
      (a) `name` 正则白名单 `^[\w.\-]+$` 或等价；
      (b) `Path.resolve().relative_to(outputs)` 两层校验；
      (c) 拒绝 `..`、绝对路径、子目录、null 字节；失败返回 400
- [ ] `_resolve_output_dir` 必须以项目根 `ROOT` 为基准：空 → `<ROOT>/outputs`，相对路径 → 拼到 ROOT 下，绝对路径 → 按原样使用
- [ ] 上传限额（默认常量，可调但不得无限制）：
      `MAX_IMAGE_COUNT_PER_RUN` / `MAX_TOTAL_FILES_PER_RUN` /
      `MAX_FILE_SIZE_BYTES` / `MAX_REQUEST_BODY_BYTES`；超限必须在
      `run_pipeline` 调用之前抛 `ValueError` 或返回 413
- [ ] 文件池卡片必须呈现：总数胶囊、类型分布行（按后缀计数降序）、每行类型 pill（图片用 `.type-img` 琥珀色区分）
- [ ] 清空 `/uploads/clear` 与单条删除 `/uploads/remove` 必须走 POST-redirect-GET（HTTP 303），防止刷新重复触发
- [ ] submit 必须有前端反馈（禁用按钮 + 状态条）
- [ ] 错误分级：输入类错误（空选、超限、格式不支持）→ 400；流水线异常 → 500；两者都保持 UI 存活并重绘表单

### app.py
- [ ] `collect_input_files` 默认跳过项目元目录（`outputs/ docs/ project_memory/ .codex/ .git/ __pycache__/ .venv/`）
- [ ] 目录 glob 模式由 `parse_inputs.SUPPORTED_EXTENSIONS` 驱动，不再硬编码
- [ ] 注入 stdout notifier（`[ingest]` 前缀），支持 `--quiet` 关闭
- [ ] `review_needed` 只承载 chunk 级问题；validation warnings 必须进入 `pipeline_notes`
- [ ] topic 层 warnings 必须进入 `pipeline_notes`（系统级），不得写入 `review_needed`
- [ ] web enrichment warnings / semantic conflict 摘要必须进入 `pipeline_notes`
- [ ] 全部输入失败/空时，`pipeline_notes` 必须追加 `"no usable input text: ..."`，主流程不崩溃
- [ ] `overview` 内包含 `failed_sources` / `empty_extracted_sources` / `ingestion_summary`
- [ ] CLI 结尾打印 `is_valid` 与 warnings 摘要
- [ ] 支持 `--config` 读取运行时配置，并在配置异常时降级默认值 + 记录 warning

## 5. 硬约束（禁止事项）

- 禁止把占位功能（高级 conflict detection、生产级服务层能力、pytest 全量套件）描述为已实现
- **禁止把图片 OCR 描述为"无依赖默认可用"；必须如实标注 opt-in 与降级语义**
- 禁止以对话中的历史记忆替代 `docs/PROJECT_STATE.md` 作为事实依据
- 禁止在 `samples/demo.md` 上让 `validation.is_valid == False` 却不解释原因
- **禁止 `service/simple_ui.py` 把任何 API 密钥以原值回渲染到 HTML**（永远走 masked 状态）
- **禁止 `service/simple_ui.py` 接受除 `outputs/` 根目录以外的路径作为下载源**
- 禁止在 web_resources 条目中遗漏 `url` 或 `relevance_reason`（当 enrichment 启用时）
- 禁止把系统级警告塞进 `review_needed`（违反 G3 中"不得使用伪 chunk_id=SYSTEM"规则）
- 禁止跳过 validation 或 validation 失败仍继续导出而不产生 pipeline_notes
- 禁止让单个文件的解析失败中断整个 pipeline（`parse_inputs` 的任何新分支都必须走"降级 + 显式记录"）
- 禁止在 UI 侧跳过上传限额（图片数 / 总数 / 单文件大小 / 请求体大小四重防线，任一破除都需同步 `docs/ACCEPTANCE.md` 更新并说明理由）
