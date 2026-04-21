# TODO

Last Updated: 2026-04-21

## 仍未完成（P0 / P1 / P2）

### P0（稳定性与验收优先）

- [ ] **API 接口联调** — 阻塞在外部：代码侧 schema / fallback / 越界拒绝 / 重试 / masked 密钥管理已就位，待真实 endpoint 与鉴权策略落地后完成联调验收。
- [ ] **Validation 策略分级** — 为小样本/OCR 场景提供 `strict/lenient` 可配置校验策略，降低“可用但被判 invalid”的误报。
- [ ] **UI HTTP 自动化测试** — 固化当前手工 smoke 场景，覆盖上传限额、下载白名单、settings 密钥不回显、错误分级。

### P1（质量与可维护性）

- [ ] **分类词库与 topic taxonomy 调优流程** — 建立基于真实资料的“unknown/unclassified 比例”回看机制。
- [ ] **输出下载体验优化** — 在不破坏路径安全边界前提下，改进 `outputs/` 子目录产物下载路径体验。

### P2（能力增强）

- [ ] **语义冲突检测升级** — 从启发式规则扩展到 NLI/向量混合策略（保留启发式快筛）。
- [ ] **主题二次整理层** — 在 topic 粗分类之上生成“每 topic 子笔记”。
- [ ] **发布治理** — 将二进制包从仓库历史迁移到 Release 资产分发（含 checksum）。

---

## 建议的下一步（按顺序；执行建议）

1. 在真实资料目录上演练 `--topic-mode local`，按结果调 `config/topic_taxonomy.json` aliases
2. 接入真实 Topic / Web Enrichment API（需外部 endpoint）
3. 二次整理层：在主题粗分类之上生成"每 topic 子笔记"
4. NLI / 向量式语义冲突检测（保留启发式作为快速筛）
5. 发布治理：将 `dist/*.exe` 迁移到 GitHub Releases，仓库只保留源码与打包脚本

---

## Changelog（按里程碑）

### 2026-04-21 · UI 收尾与桌面交付

- [x] 收尾优化：修复 `tools/web_enrichment.py` 的无效转义告警，并补充 URL 末尾标点清洗回归测试（`tests/test_phase2_features.py`）
- [x] API 协议兼容增强：`custom` + `openai_compatible` 双协议，`auto` 自动识别 DeepSeek/OpenAI 风格并补全 chat-completions endpoint
- [x] API 协助触发策略收敛：默认关闭，仅用户显式开启（CLI/UI/API 请求）才调用外部 API
- [x] `/` 对外视图与 `/lab` 调试视图分层，默认隐藏测试参数（`7d2fd23`）
- [x] 一键启动与桌面打包链路：`launch_app.py` + `scripts/build_desktop.py`（`7d2fd23`）
- [x] UI 专业视觉体系重构：CSS token / 系统字体栈含 CJK fallback / 一致圆角 / 响应式断点 / focus-ring（`5127194`，功能零改动）
- [x] 主页流程感知 Header：`API 状态` chip，只显 on/off，永不回显值（`b58fa67`）
- [x] `/settings` 完整 API 覆盖：按模块覆盖折叠栏 + 字段级清空语义（`KEY__clear` + `_write_env_pairs(clears=...)`）（`b58fa67`，后续 UI 改为内联 clear 按钮）
- [x] `/settings` 控制台紧凑化：顶部状态栏 + 主从档案布局 + 内联 clear/密钥显隐/复制 + 档案详情内聚危险操作
- [x] 治理文档同步基线：六份文档与代码对齐（`af81467`）
- [x] Flask 最小服务入口 + 入口测试（`service/flask_server.py` / `tests/test_flask_service_entry.py`）

### 2026-04-20 · MVP 主体交付

**P0 · 核心流水线稳定性**
- [x] 降低 `classify_notes` 的 `unclassified` 误伤（类别优先级 tie-break + 起始标签加成 + 分步 confidence）
- [x] `export_notes` 完整渲染 Stage 1/2/3
- [x] 分离 `review_needed`（chunk 级）与 `pipeline_notes`（系统级）
- [x] `validate_result` 消费 `failed_sources` / `empty_sources`
- [x] `chunk_notes` 单句超 `max_chars` 字符硬切兜底
- [x] `collect_input_files` 默认跳过项目元目录
- [x] 输入扩展：`.docx` 解析（python-docx）
- [x] 输入扩展：`.png / .jpg / .jpeg` opt-in OCR + 显式降级
- [x] 输入阶段结构化告知：notifier 事件流 + `ingestion_summary`
- [x] 失败源 schema：`reason` ∈ `{unsupported_file_type, file_not_found, parse_error, ocr_backend_unavailable}`
- [x] Topic Coarse Classification 层（受约束标签 + 可选 API + 降级）
- [x] 核心测试覆盖：7 份 stdlib 测试脚本（82 passed，含可选依赖 SKIP 语义）

**P1 · 流程完整性**
- [x] 可开关的最小 web enrichment（`title/url/purpose/relevance_reason` schema）
- [x] Validation 补"外部资源链接缺失"检查（仅 enrichment 启用时）
- [x] 语义冲突检测（启发式关键词规则）并接入 validation
- [x] Key points 可选 `min_confidence` 阈值（`--keypoint-min-confidence`）
- [x] docx 样式感知：`heading_path` 注入分类

**P2 · 交付链**
- [x] FastAPI 最小服务入口（`service/api_server.py` + `requirements-api.txt`）
- [x] API 接入基础资产（`.env.example` + `config/api_payload_templates.json` + `docs/API_SETUP.md`）
- [x] 运行时配置文件（`config/pipeline_config.json` + `tools/runtime_config.py`）
- [x] Markdown 分级目录折叠（`markdown_use_details`）
- [x] Docker 镜像（内置 tesseract + 中文语言包，OCR 开箱即用）

**UI 交付链**
- [x] 本地 Web UI（stdlib 实现）：文件上传、API 设置、结果展示
- [x] 最终笔记 Markdown 排版清洗：去前缀冠词 + heading_path 噪声、多源来源标注、自适应"重点速记"
- [x] 文件池 + 上传四重安全限额（图片 10 / 总数 20 / 单文件 20MB / 请求体 200MB）
- [x] 文件池类型/计数汇总 + 输出目录透明化

**安全 / 合规**
- [x] `/settings` 永不回显 API key（masked 状态 + `type=password`）
- [x] `/download` 严格白名单（仅 `outputs/` 根目录，正则 + relative_to 双层校验）
- [x] Python 3.13 前瞻：自写 `_parse_multipart` 替代已废弃的 `cgi` 模块
- [x] `collect_input_files` 修复：显式文件即使位于 `uploads/` 等 EXCLUDED 目录也应被接受
