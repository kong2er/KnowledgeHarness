# PROJECT_STATE

Last Updated: 2026-04-22

## 1) Current Project Structure

```text
KnowledgeHarness/
├── app.py                           # CLI entry; orchestrates run_pipeline
├── launch_app.py                    # one-click UI launcher (auto open browser)
├── start_ui.sh / start_ui.bat       # platform shims for launch_app.py
├── README.md / SKILL.md
├── Dockerfile / .dockerignore       # OCR-ready container
├── .env.example / .gitignore
├── requirements.txt                 # core
├── requirements-ocr.txt             # opt-in OCR backend
├── requirements-api.txt             # opt-in FastAPI service
├── requirements-flask.txt           # opt-in Flask service
├── requirements-desktop.txt         # opt-in desktop build (pyinstaller)
├── .codex/
│   └── session_rules.md
├── config/
│   ├── topic_taxonomy.json          # constrained topic label set
│   ├── api_payload_templates.json   # default API prompt/payload contract
│   └── pipeline_config.json         # runtime pipeline config
├── docs/
│   ├── ACCEPTANCE.md                # module + general gates
│   ├── AGENT_A_UI_CONTRACT.md       # Agent A UI input/visibility contract
│   ├── AGENT_B_UI_INFORMATION_ARCHITECTURE.md # Agent B UI information hierarchy
│   ├── AGENT_C_UI_USABILITY_ACCEPTANCE.md     # Agent C UI usability acceptance
│   ├── API_SETUP.md                 # API integration minimal spec
│   ├── ARCHITECTURE.md              # module relations + data contract
│   ├── ENGINEERING_REVIEW.md        # project-wide engineering audit snapshot
│   ├── HANDOFF.md                   # handoff conclusions
│   ├── PROJECT_STATE.md             # this file (truth baseline)
│   ├── UI_LAYOUT_SPEC.md            # UI layout + button hierarchy spec
│   └── TODO.md                      # open items + changelog
├── tools/                           # pipeline stages (single responsibility each)
│   ├── parse_inputs.py              # txt/md/pdf/docx + opt-in OCR + ingestion_summary
│   ├── chunk_notes.py               # paragraph → sentence → char fallback
│   ├── runtime_config.py            # pipeline_config.json deep-merge
│   ├── pipeline_runtime.py          # shared env/runtime resolver across CLI/API/UI
│   ├── topic_coarse_classify.py     # document-level topic (constrained labels)
│   ├── classify_notes.py            # chunk-level content classification
│   ├── stage_summarize.py           # stage_1 / stage_2 / stage_3
│   ├── extract_keypoints.py         # priority + confidence + dedup
│   ├── web_enrichment.py            # off/local/api/auto
│   ├── detect_semantic_conflicts.py # heuristic conflict detection
│   ├── validate_result.py           # consumes failed/empty/web/conflict signals
│   ├── export_notes.py              # JSON + Markdown (final_notes_only | full_report)
│   └── export_word.py               # result.md → result.docx
├── service/
│   ├── __init__.py                  # service package marker
│   ├── api_server.py                # minimal FastAPI service entry
│   ├── flask_server.py              # minimal Flask service entry
│   └── simple_ui.py                 # local Web UI (stdlib; no 3rd-party framework)
├── scripts/
│   ├── build_desktop.py             # pyinstaller packaging script
│   └── run_acceptance_gate.sh       # one-command acceptance gate runner
├── tests/                           # 9 stdlib-only scripts, run via `python3 tests/<name>.py`
│   ├── test_parse_inputs.py
│   ├── test_stage1_core.py
│   ├── test_topic_coarse_classify.py
│   ├── test_phase2_features.py
│   ├── test_phase3_non_api.py
│   ├── test_api_service_entry.py
│   ├── test_flask_service_entry.py
│   ├── test_ui_server_port_fallback.py
│   └── test_simple_ui.py
├── samples/                         # demo inputs: happy path + OCR path + unsupported path
├── uploads/ui_uploads/              # gitignored; UI upload pool
├── outputs/                         # gitignored; run artifacts only
└── project_memory/                  # historical chat context, non-authoritative
```

## 2) Implemented Modules

- `tools/parse_inputs.py`
  - txt / md（stdlib）
  - pdf（`pypdf`，懒加载）
  - docx（`python-docx`，懒加载）
  - docx heading 样式感知：抽取层级并注入 `heading_path`
  - **图片 `.png` / `.jpg` / `.jpeg`：opt-in OCR**，优先本地 `pytesseract + Pillow + tesseract`
  - 当 `api_assist_enabled=true` 且 API 已配置时，图片 OCR 支持 `fallback_only/auto/prefer_api` 三种协助策略；`auto` 下会在本地结果较弱时调用 API 并择优
  - 图片 API OCR 失败时仍按原降级语义回退，不中断主流程
  - 失败源统一 schema：`{source, source_name, source_type, reason, error}`；`reason` 取值 `unsupported_file_type / file_not_found / parse_error / ocr_backend_unavailable`
  - 可选 `notifier(event, payload)` 回调：事件 `detected / start / success / failed / summary`
  - 支持 OCR 语言配置：`ocr_languages` / `ocr_fallback_language`
  - 返回新增 `ingestion_summary`：`detected / supported / unsupported / succeeded / empty_extracted / failed / breakdown_by_type / supported_extensions_effective / image_extensions_opt_in / ocr_backend / image_api_assist_enabled / image_api_enhance_mode / image_api_attempted / image_api_succeeded / image_api_enhanced`

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
  - 可选 API 协助：仅在 `api_assist_enabled` 下对低置信度/未分类 chunk 做受约束补判（标签仍只允许现有 `CATEGORIES`）
  - API 失败/越界时自动降级回本地规则，并写入 warnings
  - 支持从配置注入 `keywords` / `label_hints` / `category_priority`

- `tools/topic_coarse_classify.py`
  - 文档级（source/document 粒度）主题粗分类，不替代 chunk 级功能分类
  - 本地受约束标签集合来自 `config/topic_taxonomy.json`
  - 支持 `mode=auto/local/api`
  - 支持 API 重试（`api_retries`）
  - 支持 API 协议风格：`custom` 与 `openai_compatible`（DeepSeek/OpenAI 兼容），`auto` 可自动识别并补全 `/v1/chat/completions`
  - API 输出必须落在 allowed labels 内；越界/失败/超时降级到 local/`unknown_topic`
  - 输出 `topic_classification.items/topic_groups/stats/warnings`

- `tools/runtime_config.py`
  - 加载并深度合并运行时配置（`config/pipeline_config.json`）
  - 配置异常时回退默认值并产生 warning
  - 新增 `api_assist.enabled_by_default`：控制是否默认开启 API 协助（当前默认 false）

- `tools/pipeline_runtime.py`
  - 统一 `.env` 读取（不覆盖已有系统环境变量）
  - 统一 API 配置探针（topic/web/any 三种状态）
  - 统一 `config/pipeline_config.json` + 请求覆盖参数解析，输出可直接用于 `run_pipeline` 的 kwargs
  - 保障 CLI/FastAPI/Flask/UI 在已有功能范围内保持一致策略（默认值、降级语义、配置继承）

- `tools/web_enrichment.py`
  - 可开关 enrichment（`enabled + off/local/api/auto`）
  - local 模式从用户资料抽取 URL；api/auto 失败回退 local/off
  - URL 归一化会剥离常见尾随标点（如 `) ] . ,`），避免脏链接进入资源列表
  - 支持 API 协议风格：`custom` 与 `openai_compatible`（DeepSeek/OpenAI 兼容），`auto` 可自动识别并补全 `/v1/chat/completions`
  - 支持 API 重试（`api_retries`）
  - 输出资源 schema：`title/url/purpose/relevance_reason`

- `tools/detect_semantic_conflicts.py`
  - 启发式冲突检测（声明关键词互斥）
  - 输出冲突对（`chunk_a/chunk_b/reason`）

- `tools/stage_summarize.py`
  - `stage_1` / `stage_2` / `stage_3` 始终输出三键
  - `stage_3` 支持可选 API 协助整理（固定四个列表字段，失败自动降级本地结果）

- `tools/extract_keypoints.py`
  - 按 `BUCKET_ORDER`（pitfalls → concepts → methods → examples）+ 同类内 confidence 降序
  - normalize 去重
  - 最多 `max_points`（默认 12）
  - 支持 `min_confidence` 阈值过滤（避免低置信度挤占）

- `tools/validate_result.py`
  - 支持 `validation_profile`（`strict/lenient`；默认 strict）
  - strict: 未分类比例、空主分类、重复 chunk、阶段总结缺失
  - lenient: 对小样本/OCR 场景放宽未分类与空主分类触发阈值
  - 消费 `failed_sources` / `empty_sources` 并产出 `failed_sources_present` / `empty_extracted_sources` 警告
  - enrichment 启用时校验 `web_resources` 的 `url/relevance_reason` 缺失
  - 消费语义冲突结果并产出 `semantic_conflicts_detected:<n>` 警告

- `tools/export_notes.py`
  - `result.json` + `result.md`
  - 默认导出"最终整理笔记版"（`final_notes_only=True`）：去除 classifier-facing 冠词前缀（"概念：/方法步骤：..."）与 `[heading_path: …]` 尾巴；多源时自动在顶部加 `> 本笔记由 N 份文档合并整理` 引用 + 每条带 `*（来源：xxx）*` 斜体标注；总条数 >12 且有去重新增时才输出"重点速记"节，避免重复
  - "完整报告版"（`final_notes_only=False`）保留诊断信息：完整渲染 Stage 1（theme distribution）+ Stage 2（每类 count+preview）+ Stage 3（四个子列表）、`Ingestion Summary`、`Topic Overview`、`Semantic Conflicts`、`Failed Sources`（带 `reason`）
  - 支持 `markdown_use_details`（分类区块可折叠渲染）
  - `review_needed` 与 `pipeline_notes` 分区呈现
  - `failed_sources` / `empty_extracted_sources` 仅在非空时显示

- `tools/export_word.py`
  - 从已生成的 `result.md` 转换为 `result.docx`（`python-docx`，已在 `requirements.txt`）
  - 支持 ATX 标题 / bullet / 引用块（Word `Quote` 样式，模板缺失时降级 Normal）/ 水平线（`---` → 空段落，不渲染字面量）
  - 行内 `*…*` 斜体转为真 `run.italic = True`，不残留字面量星号
  - 失败时不中断主流程；`app.run_pipeline` 会把异常写入 `pipeline_notes`

- `app.py`
  - CLI 串联全流程
  - 通过 `tools/pipeline_runtime.py` 统一加载项目根目录 `.env`（不覆盖已有系统环境变量）
  - 输入支持文件 / 目录 / glob；默认跳过项目元目录
  - 目录 glob 模式动态取自 `parse_inputs.SUPPORTED_EXTENSIONS`（docx/png/jpg/jpeg 会被自动拾取）
  - 注入 stdout notifier（`[ingest]` 前缀），可用 `--quiet` 关闭
  - 在 `chunk_notes` 后、`classify_notes` 前新增 `topic_coarse_classify`
  - 新增 CLI 参数：`--topic-mode` / `--topic-taxonomy` / `--topic-api-timeout` / `--topic-api-retries`
  - 新增 web enrichment 参数：`--enable-web-enrichment` / `--web-enrichment-mode` / `--web-enrichment-timeout` / `--web-enrichment-max-items`
  - 新增 web enrichment 重试参数：`--web-enrichment-api-retries`
  - 新增 keypoint 参数：`--keypoint-min-confidence`
  - 新增：`--keypoint-max-points`、`--validation-profile`、`--config`
  - 运行时配置驱动：chunk 长度、分类字典、OCR 语言、导出折叠（并与 API/UI 共用同一解析器）
  - 全部输入失败/为空时，`pipeline_notes` 追加 `"no usable input text"`，主流程不崩溃
  - `review_needed` 仅含 chunk 级问题；validation warnings 进 `pipeline_notes`
  - topic 层 warnings 进入 `pipeline_notes`（系统级）
  - web enrichment warnings 与 semantic conflict 摘要进入 `pipeline_notes`
  - 当用户显式选择 API 模式但 URL 未配置时，打印提示：`请接入API后使用`
  - 支持统一 API 环境变量：`KNOWLEDGEHARNESS_API_URL / KNOWLEDGEHARNESS_API_KEY`
  - API 协助策略：默认关闭，需显式开启（CLI `--enable-api-assist` / UI 勾选 / 服务请求字段 `enable_api_assist=true`）
  - 支持 `--export-docx`，可选导出 `result.docx`
  - 支持 `--full-report` 切换为完整报告版 md（默认纯笔记版）
  - CLI 结尾打印 `is_valid` 与 warnings 摘要

- `service/api_server.py`
  - 提供最小 FastAPI 服务入口（`/health`、`/pipeline/run`、`/pipeline/capabilities`）
  - 复用 `run_pipeline`，保持与 CLI 一致的降级语义
  - 与 CLI 共用 `build_pipeline_run_kwargs`：请求未传字段时继承 `config/pipeline_config.json`
  - `/health` 的 API 配置探针与 CLI/UI 统一（支持 unified URL 回退）
  - 通过 `requirements-api.txt` 进行可选依赖安装

- `service/flask_server.py`
  - 提供最小 Flask 服务入口（`/health`、`/pipeline/run`、`/pipeline/capabilities`）
  - 请求字段默认值与 `service/api_server.py` 对齐，便于互换部署
  - 与 CLI/FastAPI 共用 `build_pipeline_run_kwargs`（避免入口参数漂移）
  - 布尔字段解析支持字符串显式值（`"false"` -> False），避免 `bool("false")==True` 误判
  - 复用 `run_pipeline`，保持与 CLI/FastAPI 一致的降级语义
  - 通过 `requirements-flask.txt` 进行可选依赖安装

- `service/simple_ui.py`
  - 基于 `http.server` 的本地 Web UI，**不依赖 Flask / Jinja / cgi**（cgi 在 Python 3.13 已移除）；多部分解析由本模块内的 `_parse_multipart` 提供
  - **双栏信息架构重构（2026-04-22）**：主页面改为“左操作区 / 右状态与结果区”；左侧承载输入与主操作，右侧承载阶段状态、告警日志、结果摘要与导出入口，降低首次使用认知负担
  - **按钮层级重构（2026-04-22）**：一级主按钮为“开始整理/运行流水线”；二级按钮为“选择文件/选择文件夹/API 设置/打开结果文件/打开输出目录”；次级操作收敛为“重置本次选择/清空列表/删除”
  - **文件导入能力（2026-04-22）**：支持“选择文件夹”入口（浏览器目录选择，仍写入同一 `upload_files` 字段），并保留历史文件池勾选复用
  - **文件池**（`uploads/ui_uploads/`）：首次上传后的文件被保留并在 UI 内列出，每条带类型 pill + 大小 + mtime + "删除"按钮；勾选即可再次运行，不需要重上传。顶部有"清空全部"、"共 N 个"胶囊、类型分布行（如 `.docx × 2 · .png × 3 · .md × 1`）
  - **上传限额**（默认常量，位于 `service/simple_ui.py` 顶部可调）：
    - `MAX_IMAGE_COUNT_PER_RUN = 10`（png/jpg/jpeg 合计）
    - `MAX_TOTAL_FILES_PER_RUN = 20`（全格式）
    - `MAX_FILE_SIZE_BYTES = 20 MB`
    - `MAX_REQUEST_BODY_BYTES = 200 MB`（`Content-Length` 预校验，防 OOM）
  - **输出目录透明化**：相对路径一律以项目根目录（`ROOT`）为基准解析；UI 实时显示"本次将写入：<abs path>"；若不在 `outputs/` 之下则显示"下载链接不可用，需手动打开路径"警告
  - **下载端点 `GET /download?name=<basename>`**：严格限制在 `outputs/` 根目录，`name` 白名单正则 + `Path.resolve().relative_to()` 二层校验；任何路径穿越（`../` / 绝对路径 / 子目录）返回 400
  - **输出目录浏览页 `GET /outputs`（2026-04-22）**：新增只读目录浏览页，用于“打开输出目录”操作闭环；仅提供文件列表与受限下载入口（下载仍遵循 `outputs/` 根目录白名单）
  - **API 设置页 `/settings`**：密钥字段使用 `type=password` 且**从不回显当前值**；状态用"已配置（末 4 位：···abcd）"掩码形式呈现；留空提交 = 保持原值，不会误清空
  - **多 API 档案管理（2026-04-21）**：支持将当前 API 配置保存为多个档案（`config/api_profiles.json`）、查看档案详情（密钥掩码）、应用（不设默认/设默认）、用当前环境覆盖档案、删除档案，以及一键清空当前 API 环境配置；运行页支持按次选择“API 配置档案”
  - **双视图**：`/` 对外使用视图（默认，隐藏测试/调试信息）与 `/lab` 调试视图（显示测试参数与诊断信息）
  - 调试视图默认禁用：仅 `KH_UI_ENABLE_LAB=1` 时可访问 `/lab`；首页入口还需 `KH_UI_SHOW_LAB_LINK=1`
  - **流程感知 Header（2026-04-21）**：主页标题旁展示 `API 状态` chip；状态判断与 CLI/API 服务入口共用统一探针；只显示 on/off 状态，**绝不回显任何 URL/Key 值**；点击跳转 `/settings`
  - **完整 API 设置覆盖（2026-04-21）**：`/settings` 现分为"主设置"（`KNOWLEDGEHARNESS_API_URL/KEY`）与"按模块覆盖"（`TOPIC_CLASSIFIER_*` + `IMAGE_OCR_*` + `WEB_ENRICHMENT_*`，默认折叠）；字段清空从独立 checkbox 收敛为输入框内联 clear（`×`）控制，提交时通过 `KEY__clear` 标记驱动 `_write_env_pairs(clears=...)` 把 `.env` 对应行改写为 `KEY=`（保留文件结构）并同步重置当前进程 `os.environ`
  - **API 设置控制台紧凑化（2026-04-21）**：`/settings` 顶部改为全局状态栏（激活档案/档案数/模块就绪/环境状态），主体改为"基础配置 + 档案主从区"布局；支持密钥显隐（👁）、字段复制、全局 toast 反馈；危险操作聚合到选中档案详情内并带二次确认
  - **专业重设计（2026-04-21，纯视觉）**：统一 CSS token 配色（`--bg/--surface/--text/--accent` 等）、系统字体栈（CJK fallback）、一致圆角（10/6/999）、响应式断点（`max-width: 720px`）；功能未变
  - **进度反馈**：submit 时 inline JS 禁用按钮 + 顶部显示"处理中"状态条
  - **端口占用回退（2026-04-22）**：命令行直启 `python3 service/simple_ui.py --port <p>` 在端口冲突时会自动尝试后续端口（默认最多 30 次），并打印实际启动端口；支持 `--max-port-tries`
  - **结果区（2026-04-22）**：右栏固定包含处理阶段、成功/失败/空文本统计、告警与 notes、结果摘要、主题粗分类简报与“打开结果/打开目录”动作；调试视图额外提供完整摘要详情
  - 错误分级：`ValueError` → 400（输入错误，如超限、不支持格式、空选）；其他异常 → 500（流水线异常），均保持 UI 存活
  - 自动加载项目根 `.env`（不覆盖已有系统环境变量）
  - 运行按钮调用与 CLI/FastAPI/Flask 共用 `build_pipeline_run_kwargs`，确保配置继承和默认行为一致

- `launch_app.py`
  - 一键启动本地 UI 并自动打开浏览器（便于非技术用户直接使用）
  - 端口占用时自动从起始端口向后探测可用端口
  - 环境变量加载统一复用 `tools/pipeline_runtime.load_local_env`

- `scripts/build_desktop.py`
  - 通过 PyInstaller 打包桌面可执行文件（`dist/`）

- `scripts/run_acceptance_gate.sh`
  - 一键执行验收门禁：9 份测试脚本 + `samples/demo.md` smoke
  - 自动检查 `result.json` 顶层必需键与 `validation.is_valid == True`

- `tests/test_parse_inputs.py`
  - 仅覆盖"输入扩展与上传告知"模块的核心路径（不含 pytest 依赖，可直接 `python3` 运行）
  - 用例：extension surface / unsupported / empty / file_not_found / docx happy / OCR 缺失降级 / notifier 事件流 / encrypted pdf parse_error / docx heading_path 注入 / 图片 API fallback / 图片 API 自动增强择优

- `tests/test_topic_coarse_classify.py`
  - local/unknown/out-of-scope fallback/api exception/taxonomy fallback

- `tests/test_stage1_core.py`
  - chunk/classify/validate/export/app 的阶段 1 回归

- `tests/test_phase2_features.py`
  - web enrichment local schema
  - validation 的 web 字段检查（仅 enrichment enabled）
  - semantic conflict 检测
  - topic api retry 行为

- `tests/test_phase3_non_api.py`
  - runtime config merge
  - markdown details export
  - keypoint max_points 上限

- `tests/test_api_service_entry.py`
  - FastAPI 服务入口存在性检查（fastapi 缺失时 skip）

- `tests/test_flask_service_entry.py`
  - Flask 服务入口路由、请求解析、健康检查与 400 验证路径检查

- `tests/test_ui_server_port_fallback.py`
  - 端口占用时 `create_server` 自动回退语义 + `auto_fallback=False` 抛错语义
  - 受限环境（禁止 socket bind）按 SKIP 语义退出，不阻断门禁

- `tests/test_simple_ui.py`
  - `simple_ui` HTTP 关键路径回归：settings 密钥不回显、下载白名单、输入类 400、上传限额、流水线异常 500
  - 受限环境（禁止 socket bind）按 SKIP 语义退出，不阻断门禁

## 3) Not Implemented / Placeholder

- API 接口联调待外部接口规范与鉴权信息就绪
- 全量 pytest 自动化测试套件未建立；当前为 **9 份 stdlib-only 测试脚本**（可直接 `python3 tests/<name>.py` 运行）：
  `test_parse_inputs.py` / `test_stage1_core.py` / `test_topic_coarse_classify.py` /
  `test_phase2_features.py` / `test_phase3_non_api.py` / `test_api_service_entry.py` /
  `test_flask_service_entry.py` / `test_ui_server_port_fallback.py` / `test_simple_ui.py`
  当前基线为 **91+ 条通过断言（含可选依赖 SKIP 语义）**；受环境能力影响（如 socket bind 权限）部分用例会按 SKIP 语义执行
- 图片 OCR 在默认环境下若无本地 OCR 依赖不会走本地识别；仅在显式开启 API 协助且 API 可用时可走图片 API OCR 增强。容器内（`Dockerfile`）默认具备本地 OCR 能力
- Topic API 仅提供可选接入点；默认运行不依赖外部 API
- Web enrichment API 仅提供可选接入点；默认可走 local 模式
- 语义冲突检测当前为启发式规则版，非 NLI 语义推理
- 运行时配置当前为 JSON 文件方案；未接入远程配置中心
- UI 为单用户设计，无会话/鉴权/并发隔离；`uploads/ui_uploads/` 为进程共享池，不做 TTL 清理

## 4) Known Issues

1. 规则分类依赖关键词字典，未在字典覆盖的表述仍会进 `unclassified`。
2. `_leading_label` 只识别"短前缀 + 中/英冒号"，纯口语化段落识别率低。
3. 图片 OCR 的语言包（`chi_sim`）需单独安装，否则会回退到 `eng`；混合中英图片在仅 `eng` 的环境下可能漏字。
4. topic 粗分类当前以 alias 命中为主；当领域词库覆盖不足时会降级 `unknown_topic`。
5. web enrichment local 模式只会提取用户资料中已有链接，不会主动联网搜索。
6. encrypted PDF 降级测试依赖 `pypdf` 可用；依赖缺失时测试会 skip。
7. Word 导出只覆盖 `_render_final_notes_markdown` 实际输出的 markdown 子集（标题 / bullet / 引用 / 斜体 / 水平线）；一般 markdown 语法（表格、代码块、链接文本）未处理，超出本用途会回退为纯文本段落。
8. UI 下载端点只对 `outputs/` 根目录生效；`outputs/` 子目录 或非 `outputs/` 的绝对路径需手动打开文件系统路径（UI 会给出明确提示）。

## 5) Acceptance Gate

- 所有修改必须通过 `docs/ACCEPTANCE.md` 中的 §3 通用 Gate 和对应模块 §4 条目。
- 输入扩展与上传告知模块的验收条目见 `docs/ACCEPTANCE.md` §4 "parse_inputs (Input Expansion)"。
- 硬约束见 `docs/ACCEPTANCE.md` §5 与 `SKILL.md` Prohibitions。

## 6) Truth Alignment Statement

本文件只描述仓库当前真实状态。未实现能力不得写成"已实现"。
若文档与代码冲突：先修正其中一方以恢复一致，再继续开发。

## 7) Engineering Snapshot (2026-04-22)

参考总览：`docs/ENGINEERING_REVIEW.md`。

当日审计结果（命令与结果已固化在 ENGINEERING_REVIEW）：

- 全量 `tests/test_*.py` 通过（含可选依赖 SKIP 语义）。
- `samples/demo.md` 与 `samples/` 混合输入：`validation.is_valid=True`。
- `samples/ingest_demo.docx` / `samples/ingest_demo.png`：在 `strict` 下可能触发 warnings；可用 `validation_profile=lenient` 降低小样本误报。

当前最值得优先优化的方向：

1. 真实 API 联调验收闭环（外部依赖到位后执行）。
2. 词库/taxonomy 基于真实语料的持续调优流程。
3. `outputs/` 子目录下载体验（不放松安全边界前提）。

封包状态（Windows）：

- 当前仓库已包含最新提交的 `.exe` 封包：`dist/KnowledgeHarness.exe`
- 对应元信息：`dist/KnowledgeHarness.exe.buildinfo.json`
- 封包时间：`2026-04-22 21:03:58 +08:00`
- 封包 SHA256：`b01276328c72d95c948d27fff13f8f97c17cd6a4d5bd6353e3501145162fb695`
