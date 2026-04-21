# TODO

Last Updated: 2026-04-21

## 仍未完成（1 项，非阻塞）

- [ ] **API 接口联调** — 阻塞在外部：代码侧 schema / fallback / 越界拒绝 / 重试 / masked 密钥管理全部就位，等真实 API URL 与鉴权信息即可接。

---

## 建议的下一步（按顺序；非 TODO 清单）

1. 在真实资料目录上演练 `--topic-mode local`，按结果调 `config/topic_taxonomy.json` aliases
2. 接入真实 Topic / Web Enrichment API（需外部 endpoint）
3. 二次整理层：在主题粗分类之上生成"每 topic 子笔记"
4. NLI / 向量式语义冲突检测（保留启发式作为快速筛）
5. UI HTTP 层自动化测试：把 curl 验过的 8 个场景固化成 `tests/test_simple_ui.py`

---

## Changelog（按里程碑）

### 2026-04-21 · UI 收尾与桌面交付

- [x] `/` 对外视图与 `/lab` 调试视图分层，默认隐藏测试参数（`7d2fd23`）
- [x] 一键启动与桌面打包链路：`launch_app.py` + `scripts/build_desktop.py`（`7d2fd23`）
- [x] UI 专业视觉体系重构：CSS token / 系统字体栈含 CJK fallback / 一致圆角 / 响应式断点 / focus-ring（`5127194`，功能零改动）
- [x] 主页流程感知 Header：`API 状态` chip，只显 on/off，永不回显值（`b58fa67`）
- [x] `/settings` 完整 API 覆盖：按模块覆盖折叠栏 + 每字段"清空此字段" checkbox + `_write_env_pairs(clears=...)` 语义（`b58fa67`）
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
- [x] 核心测试覆盖：7 份 stdlib 测试脚本（74 passed + 可选 SKIP）

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
