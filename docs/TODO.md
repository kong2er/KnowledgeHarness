# TODO (Priority Ordered)

## P0

- [x] ~~降低 `classify_notes` 的 `unclassified` 误伤~~（2026-04-20：改为类别优先级 tie-break + 起始标签加成 + 分步 confidence）
- [x] ~~`export_notes` 完整渲染 Stage 1/2/3~~（2026-04-20）
- [x] ~~分离 `review_needed` 与系统级警告（`pipeline_notes`）~~（2026-04-20）
- [x] ~~`validate_result` 消费 `failed_sources` / `empty_sources`~~（2026-04-20）
- [x] ~~`chunk_notes` 单句超 `max_chars` 的字符硬切兜底~~（2026-04-20）
- [x] ~~`collect_input_files` 默认跳过项目元目录~~（2026-04-20）
- [x] ~~输入扩展：`.docx` 解析（python-docx）~~（2026-04-20）
- [x] ~~输入扩展：`.png / .jpg / .jpeg` opt-in OCR + 显式降级~~（2026-04-20）
- [x] ~~输入阶段结构化告知：notifier 事件流 + `ingestion_summary`~~（2026-04-20）
- [x] ~~失败源 schema 扩展：`reason` ∈ {unsupported_file_type, file_not_found, parse_error, ocr_backend_unavailable}~~（2026-04-20）
- [x] ~~`tests/test_parse_inputs.py` 最小 stdlib 测试~~（2026-04-20）
- [x] ~~新增 Topic Coarse Classification Layer（受约束标签 + 可选 API + 降级）~~（2026-04-20）
- [x] ~~建立最小自动化测试覆盖其他模块（`chunk_notes / classify_notes / validate_result / export_notes`）~~（2026-04-20：`tests/test_stage1_core.py`）
- [x] ~~为 `topic_coarse_classify` 增加最小测试（local/api fallback/out-of-scope label）~~（2026-04-20：`tests/test_topic_coarse_classify.py`）
- [x] ~~为 `app.py` 增加失败场景回归用例（空输入、仅失败输入、PDF 加密、混合类型输入等）~~（2026-04-20：`tests/test_stage1_core.py` + `tests/test_parse_inputs.py::test_pdf_encrypted_fails_gracefully`）

## P1

- [x] ~~接入可开关的最小 web enrichment（保留 `title / url / purpose / relevance_reason`）~~（2026-04-20）
- [x] ~~在 validation 中补"外部资源链接缺失"检查（仅在 web enrichment 启用时）~~（2026-04-20）
- [x] ~~引入语义冲突检测（至少关键词冲突规则）并接入 validation~~（2026-04-20）
- [x] ~~按 `confidence` 给 key_points 加可选阈值（避免低 conf 占位挤掉高 conf）~~（2026-04-20：`--keypoint-min-confidence`）
- [x] ~~为 docx 补"样式感知"扩展：抽取 heading 层级作为显式 label 注入分类~~（2026-04-20：`heading_path` 注入）

## P2

- [x] ~~提供 FastAPI 最小服务入口~~（2026-04-20：`service/api_server.py` + `requirements-api.txt`）
- [ ] 提供 Flask 最小服务入口（可选；当前已有 FastAPI）
- [ ] API 接口联调（等待外部 API 规范与鉴权信息就绪后再接入）
- [x] ~~补齐 API 接入基础资产（`.env.example` + `config/api_payload_templates.json` + `docs/API_SETUP.md`）~~（2026-04-20）
- [x] ~~增加配置文件（阈值、分块长度、分类关键词、LABEL_HINTS、OCR 语言）~~（2026-04-20：`config/pipeline_config.json` + `tools/runtime_config.py`）
- [x] ~~Markdown 导出支持分级目录折叠，提高长笔记可读性~~（2026-04-20：`markdown_use_details`）
- [x] ~~打包 Docker 镜像（内置 tesseract + 中文语言包），让 OCR 从 opt-in 变"开箱即用"~~（2026-04-20：`Dockerfile`）

## P1+（UI 交付链，本轮响应式补齐，非事前登记）

- [x] ~~提供最简本地 Web UI（stdlib 实现）：文件上传、API 设置、结果展示~~（2026-04-20：`service/simple_ui.py`）
- [x] ~~清洗最终笔记 Markdown 排版（去前缀冠词与 heading_path 噪声、多源来源标注、自适应"重点速记"）~~（2026-04-20：`_render_final_notes_markdown` 与 `export_word` 的 Quote/italic/HR 支持）
- [x] ~~UI 已上传文件池 + 上传安全限额（图片 10 / 总数 20 / 单文件 20MB / 请求体 200MB）~~（2026-04-20：`service/simple_ui.py` 常量 + `_store_uploaded_files` 校验）
- [x] ~~UI 文件池类型/计数汇总 + 输出目录透明化（以项目根为基准解析，实时显示"本次将写入"的绝对路径）~~（2026-04-20）
- [x] ~~UI 对外视图与调试视图分层（`/` 与 `/lab`），默认隐藏测试参数~~（2026-04-21：`7d2fd23`）
- [x] ~~新增一键启动与桌面打包链路（`launch_app.py` + `scripts/build_desktop.py`）~~（2026-04-21：`7d2fd23`）
- [x] ~~UI 专业视觉体系重构（CSS token 配色 / 系统字体栈含 CJK fallback / 一致圆角 / 响应式断点 / focus-ring）~~（2026-04-21：`5127194`，功能零改动）
- [x] ~~主页流程感知 Header（`API 状态` chip，只显 on/off，永不回显值）~~（2026-04-21：`b58fa67`）
- [x] ~~`/settings` 完整 API 覆盖（按模块覆盖折叠栏 + 每字段"清空此字段" checkbox + `_write_env_pairs(clears=...)` 语义）~~（2026-04-21：`b58fa67`）

## P1+（安全 / 合规，本轮响应式补齐）

- [x] ~~`/settings` 不再把 API key 明文回渲染进 HTML（改为 masked 状态 + `type=password`）~~（2026-04-20）
- [x] ~~`/download` 严格白名单（仅 `outputs/` 根目录，正则 + relative_to 双层校验）~~（2026-04-20）
- [x] ~~`cgi` 模块被 Python 3.13 移除的提前规避（自写 `_parse_multipart`）~~（2026-04-20）
- [x] ~~`collect_input_files` 修复：显式文件路径即使位于 EXCLUDED_DIR_NAMES（如 `uploads/`）也应被接受~~（2026-04-20）
