# TODO

Last Updated: 2026-04-22

## 仍未完成（P0 / P1 / P2）

### P0（稳定性与验收优先）

- [ ] **API 接口联调** — 阻塞在外部：代码侧 schema / fallback / 越界拒绝 / 重试 / masked 密钥管理已就位，待真实 endpoint 与鉴权策略落地后完成联调验收。
- [x] **Validation 策略分级** — 已支持 `strict/lenient` 可配置校验策略，降低小样本/OCR 场景误报。
- [x] **UI HTTP 自动化测试** — 已新增 `tests/test_simple_ui.py` 覆盖上传限额、下载白名单、settings 密钥不回显、错误分级（受限环境按 SKIP 语义执行）。

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

### 2026-04-22 · UI 布局与按键可用性重构（仅已有功能）

- [x] `service/simple_ui.py` 主页面改为“左操作区 / 右状态与结果区”双栏结构（移动端自动单栏）
- [x] 按钮层级重构：一级主按钮（开始整理）与二/三级动作分层
- [x] 文件导入增强：新增“选择文件夹”入口，保留“选择文件”与历史文件池复用
- [x] 右栏状态区固定展示：阶段、成功/失败/空文本/处理文件数、告警与 notes
- [x] 结果闭环增强：新增“打开输出目录”（`/outputs` 页面）与“打开结果文件”动作
- [x] 新增 UI/Agent 专用文档：`UI_LAYOUT_SPEC` + `AGENT_A/B/C_UI_*`
- [x] 回归检查：`python3 -m py_compile service/simple_ui.py` 通过；`tests/test_simple_ui.py`、`tests/test_ui_server_port_fallback.py` 在受限环境按 SKIP 语义执行

### 2026-04-22 · 图片 API OCR 增强策略 + UI 交互优化（不扩范围）

- [x] `parse_inputs` 图片链路支持 `fallback_only / auto / prefer_api` 三档 API 协助策略
- [x] `auto` 策略下支持“本地 OCR 与 API OCR 择优覆盖”，并新增 `image_api_enhanced` 统计
- [x] `ingestion_summary` 增补 `image_api_enhance_mode / image_api_enhanced`
- [x] 运行时配置补齐 OCR 增强参数：`config/pipeline_config.json` + `tools/runtime_config.py`
- [x] UI 优化：运行页新增 `validation_profile` 选择、图片增强策略提示、摘要卡展示图片 API 尝试/生效/增强统计
- [x] API 设置页模块就绪计数修正为 `3`（Topic / Image OCR / Web Enrichment）
- [x] 回归测试：`tests/test_parse_inputs.py` 新增“自动增强择优覆盖/保留本地更优结果”用例

### 2026-04-22 · 未完成项收尾（Validation + UI HTTP 测试）

- [x] `tools/validate_result.py` 增加 `validation_profile`（`strict/lenient`）策略分级
- [x] `config/pipeline_config.json` + `tools/runtime_config.py` 新增 `validation.profile` 运行时配置
- [x] CLI/FastAPI/Flask 入口新增 `validation_profile` 参数透传（经 `build_pipeline_run_kwargs` 统一解析）
- [x] 新增 `tests/test_simple_ui.py`：覆盖 settings 密钥不回显、下载白名单、输入类 400、流水线异常 500、图片数量上限
- [x] 相关回归：`tests/test_stage1_core.py` / `tests/test_phase3_non_api.py` 增补 validation profile 断言

### 2026-04-22 · 运行结构一致性优化（不扩功能）

- [x] 新增 `tools/pipeline_runtime.py`：统一 `.env` 加载、API 配置探针、`run_pipeline` 参数解析
- [x] CLI/FastAPI/Flask/UI 全入口改为共享参数解析层，修复“入口默认值策略漂移”风险
- [x] Flask 请求解析强化：布尔字符串显式解析（`"false"` 不再被误判为 True）
- [x] `tests/test_flask_service_entry.py` 增加配置继承与布尔解析回归断言

### 2026-04-22 · UI 端口占用修复（不扩功能）

- [x] 修复 `python3 service/simple_ui.py --port 8765` 在端口占用时报错退出的问题：改为自动回退后续可用端口
- [x] `service/simple_ui.py` 新增 `--max-port-tries` 参数，控制端口回退尝试范围
- [x] `launch_app.py` 环境加载改为复用 `tools/pipeline_runtime.load_local_env`（修复旧符号引用风险）
- [x] 新增 `tests/test_ui_server_port_fallback.py` 回归测试（受限环境按 SKIP 语义执行）

### 2026-04-22 · API 协助范围补齐（分类 + 整理）

- [x] `tools/classify_notes.py` 增加受约束 API 协助（仅低置信度/未分类 chunk 触发；标签边界仍是 `CATEGORIES`）
- [x] `tools/stage_summarize.py` 增加 Stage 3 可选 API 协助整理（固定结构 + 失败降级）
- [x] `app.py` 接入并将新 warnings 写入 `pipeline_notes`
- [x] 更新 `config/api_payload_templates.json`、`.env.example`、`docs/API_SETUP.md`
- [x] 新增回归：`tests/test_phase2_features.py` 覆盖分类 API 补判与 Stage 3 API 整理

### 2026-04-22 · 图片读取增强（API OCR 可选补偿）

- [x] `tools/parse_inputs.py` 增加图片读取链路：本地 OCR 优先，API 协助开启时可走图片 API OCR 补偿
- [x] 新增图片 API OCR 配置项与模板：`.env.example` + `config/api_payload_templates.json`
- [x] `app.py`/`pipeline_runtime.py` 接入图片 API OCR timeout/retry 参数透传
- [x] 回归测试：`tests/test_parse_inputs.py` 增加“本地 OCR 不可用时 API OCR 回退成功”用例

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
