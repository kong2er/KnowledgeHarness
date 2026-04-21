# PROJECT_STATE

Last Updated: 2026-04-21

## 1) Current Project Structure

```text
KnowledgeHarness/
├── .codex/
│   └── session_rules.md
├── .gitignore
├── .env.example
├── README.md
├── SKILL.md
├── launch_app.py                   # one-click launcher (auto open browser)
├── start_ui.sh
├── start_ui.bat
├── requirements-api.txt             # FastAPI service deps (optional)
├── requirements-desktop.txt         # desktop build deps (optional)
├── app.py
├── requirements.txt
├── requirements-ocr.txt             # opt-in OCR backend
├── config/
│   ├── topic_taxonomy.json          # constrained topic label set
│   ├── api_payload_templates.json   # default API prompt/payload contract
│   └── pipeline_config.json         # runtime pipeline config
├── Dockerfile
├── .dockerignore
├── docs/
│   ├── ACCEPTANCE.md
│   ├── API_SETUP.md
│   ├── ARCHITECTURE.md
│   ├── HANDOFF.md
│   ├── PROJECT_STATE.md
│   └── TODO.md
├── tools/
│   ├── __init__.py
│   ├── parse_inputs.py
│   ├── chunk_notes.py
│   ├── classify_notes.py
│   ├── detect_semantic_conflicts.py
│   ├── topic_coarse_classify.py
│   ├── web_enrichment.py
│   ├── runtime_config.py
│   ├── stage_summarize.py
│   ├── extract_keypoints.py
│   ├── validate_result.py
│   ├── export_notes.py
│   └── export_word.py
├── service/
│   ├── api_server.py                # minimal FastAPI service entry
│   └── simple_ui.py                 # local Web UI (stdlib; no 3rd-party framework)
├── scripts/
│   └── build_desktop.py             # pyinstaller packaging script
├── tests/
│   ├── __init__.py
│   ├── test_parse_inputs.py         # stdlib-only; runs via `python3 tests/...`
│   ├── test_topic_coarse_classify.py
│   ├── test_stage1_core.py
│   ├── test_phase2_features.py
│   ├── test_phase3_non_api.py
│   └── test_api_service_entry.py
├── samples/
│   ├── demo.md
│   ├── ingest_demo.docx             # docx happy path
│   ├── ingest_demo.png               # image; triggers OCR or degrade
│   └── unsupported_demo.log          # unsupported_file_type path
├── uploads/                          # gitignored; UI upload pool
│   └── ui_uploads/
├── outputs/                          # gitignored; run artifacts only
│   ├── result.json
│   └── result.md
└── project_memory/                   # historical chat context, non-authoritative
    ├── 01_readme_baseline.md
    ├── 02_skill_draft.md
    ├── 03_mvp_task_constraints.md
    └── MEMORY_INDEX.md
```

## 2) Implemented Modules

- `tools/parse_inputs.py`
  - txt / md（stdlib）
  - pdf（`pypdf`，懒加载）
  - docx（`python-docx`，懒加载）
  - docx heading 样式感知：抽取层级并注入 `heading_path`
  - **图片 `.png` / `.jpg` / `.jpeg`：opt-in OCR**，探测 `pytesseract` + `Pillow` + `tesseract` 二进制三者齐全才走真 OCR；任一缺失则 `failed_sources[*].reason = "ocr_backend_unavailable"`（不伪装成功）
  - 失败源统一 schema：`{source, source_name, source_type, reason, error}`；`reason` 取值 `unsupported_file_type / file_not_found / parse_error / ocr_backend_unavailable`
  - 可选 `notifier(event, payload)` 回调：事件 `detected / start / success / failed / summary`
  - 支持 OCR 语言配置：`ocr_languages` / `ocr_fallback_language`
  - 返回新增 `ingestion_summary`：`detected / supported / unsupported / succeeded / empty_extracted / failed / breakdown_by_type / supported_extensions_effective / image_extensions_opt_in / ocr_backend`

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
  - 支持从配置注入 `keywords` / `label_hints` / `category_priority`

- `tools/topic_coarse_classify.py`
  - 文档级（source/document 粒度）主题粗分类，不替代 chunk 级功能分类
  - 本地受约束标签集合来自 `config/topic_taxonomy.json`
  - 支持 `mode=auto/local/api`
  - 支持 API 重试（`api_retries`）
  - API 输出必须落在 allowed labels 内；越界/失败/超时降级到 local/`unknown_topic`
  - 输出 `topic_classification.items/topic_groups/stats/warnings`

- `tools/runtime_config.py`
  - 加载并深度合并运行时配置（`config/pipeline_config.json`）
  - 配置异常时回退默认值并产生 warning

- `tools/web_enrichment.py`
  - 可开关 enrichment（`enabled + off/local/api/auto`）
  - local 模式从用户资料抽取 URL；api/auto 失败回退 local/off
  - 输出资源 schema：`title/url/purpose/relevance_reason`

- `tools/detect_semantic_conflicts.py`
  - 启发式冲突检测（声明关键词互斥）
  - 输出冲突对（`chunk_a/chunk_b/reason`）

- `tools/stage_summarize.py`
  - `stage_1` / `stage_2` / `stage_3` 始终输出三键

- `tools/extract_keypoints.py`
  - 按 `BUCKET_ORDER`（pitfalls → concepts → methods → examples）+ 同类内 confidence 降序
  - normalize 去重
  - 最多 `max_points`（默认 12）
  - 支持 `min_confidence` 阈值过滤（避免低置信度挤占）

- `tools/validate_result.py`
  - 未分类比例、空主分类、重复 chunk、阶段总结缺失
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
  - 自动加载项目根目录 `.env`（不覆盖已有系统环境变量）
  - 输入支持文件 / 目录 / glob；默认跳过项目元目录
  - 目录 glob 模式动态取自 `parse_inputs.SUPPORTED_EXTENSIONS`（docx/png/jpg/jpeg 会被自动拾取）
  - 注入 stdout notifier（`[ingest]` 前缀），可用 `--quiet` 关闭
  - 在 `chunk_notes` 后、`classify_notes` 前新增 `topic_coarse_classify`
  - 新增 CLI 参数：`--topic-mode` / `--topic-taxonomy` / `--topic-api-timeout` / `--topic-api-retries`
  - 新增 web enrichment 参数：`--enable-web-enrichment` / `--web-enrichment-mode` / `--web-enrichment-timeout` / `--web-enrichment-max-items`
  - 新增 keypoint 参数：`--keypoint-min-confidence`
  - 新增：`--keypoint-max-points`、`--config`
  - 运行时配置驱动：chunk 长度、分类字典、OCR 语言、导出折叠
  - 全部输入失败/为空时，`pipeline_notes` 追加 `"no usable input text"`，主流程不崩溃
  - `review_needed` 仅含 chunk 级问题；validation warnings 进 `pipeline_notes`
  - topic 层 warnings 进入 `pipeline_notes`（系统级）
  - web enrichment warnings 与 semantic conflict 摘要进入 `pipeline_notes`
  - 当用户显式选择 API 模式但 URL 未配置时，打印提示：`请接入API后使用`
  - 支持统一 API 环境变量：`KNOWLEDGEHARNESS_API_URL / KNOWLEDGEHARNESS_API_KEY`
  - 支持 `--export-docx`，可选导出 `result.docx`
  - 支持 `--full-report` 切换为完整报告版 md（默认纯笔记版）
  - CLI 结尾打印 `is_valid` 与 warnings 摘要

- `service/api_server.py`
  - 提供最小 FastAPI 服务入口（`/health`、`/pipeline/run`、`/pipeline/capabilities`）
  - 复用 `run_pipeline`，保持与 CLI 一致的降级语义
  - 通过 `requirements-api.txt` 进行可选依赖安装

- `service/simple_ui.py`
  - 基于 `http.server` 的本地 Web UI，**不依赖 Flask / Jinja / cgi**（cgi 在 Python 3.13 已移除）；多部分解析由本模块内的 `_parse_multipart` 提供
  - **文件池**（`uploads/ui_uploads/`）：首次上传后的文件被保留并在 UI 内列出，每条带类型 pill + 大小 + mtime + "删除"按钮；勾选即可再次运行，不需要重上传。顶部有"清空全部"、"共 N 个"胶囊、类型分布行（如 `.docx × 2 · .png × 3 · .md × 1`）
  - **上传限额**（默认常量，位于 `service/simple_ui.py` 顶部可调）：
    - `MAX_IMAGE_COUNT_PER_RUN = 10`（png/jpg/jpeg 合计）
    - `MAX_TOTAL_FILES_PER_RUN = 20`（全格式）
    - `MAX_FILE_SIZE_BYTES = 20 MB`
    - `MAX_REQUEST_BODY_BYTES = 200 MB`（`Content-Length` 预校验，防 OOM）
  - **输出目录透明化**：相对路径一律以项目根目录（`ROOT`）为基准解析；UI 实时显示"本次将写入：<abs path>"；若不在 `outputs/` 之下则显示"下载链接不可用，需手动打开路径"警告
  - **下载端点 `GET /download?name=<basename>`**：严格限制在 `outputs/` 根目录，`name` 白名单正则 + `Path.resolve().relative_to()` 二层校验；任何路径穿越（`../` / 绝对路径 / 子目录）返回 400
  - **API 设置页 `/settings`**：密钥字段使用 `type=password` 且**从不回显当前值**；状态用"已配置（末 4 位：···abcd）"掩码形式呈现；留空提交 = 保持原值，不会误清空
  - **双视图**：`/` 对外使用视图（默认，隐藏测试/调试信息）与 `/lab` 调试视图（显示测试参数与诊断信息）
  - **流程感知 Header（2026-04-21）**：主页标题旁展示 `API 状态` chip，读取 `KNOWLEDGEHARNESS_API_URL` / `TOPIC_CLASSIFIER_API_URL` / `WEB_ENRICHMENT_API_URL` 任一存在即显示"API 已配置"，否则显示"本地模式"；只显示 on/off 状态，**绝不回显任何 URL/Key 值**；点击跳转 `/settings`
  - **完整 API 设置覆盖（2026-04-21）**：`/settings` 现分为"主设置"（`KNOWLEDGEHARNESS_API_URL/KEY`，默认展开）与"按模块覆盖"（`TOPIC_CLASSIFIER_API_URL/KEY/TEMPLATE` + `WEB_ENRICHMENT_API_URL/KEY/TEMPLATE`，默认折叠）；每个字段新增"清空此字段" checkbox，配合 `_write_env_pairs(clears=...)` 把 `.env` 对应行改写为 `KEY=` 形式（保留文件结构）并同步重置当前进程 `os.environ`
  - **专业重设计（2026-04-21，纯视觉）**：统一 CSS token 配色（`--bg/--surface/--text/--accent` 等）、系统字体栈（CJK fallback）、一致圆角（10/6/999）、响应式断点（`max-width: 720px`）；功能未变
  - **进度反馈**：submit 时 inline JS 禁用按钮 + 顶部显示"处理中"状态条
  - **结果页**：对外视图仅展示最终笔记下载（MD / DOCX）与预览；调试视图额外展示摘要诊断与 JSON 下载
  - 错误分级：`ValueError` → 400（输入错误，如超限、不支持格式、空选）；其他异常 → 500（流水线异常），均保持 UI 存活
  - 自动加载项目根 `.env`（不覆盖已有系统环境变量）

- `launch_app.py`
  - 一键启动本地 UI 并自动打开浏览器（便于非技术用户直接使用）
  - 端口占用时自动从起始端口向后探测可用端口

- `scripts/build_desktop.py`
  - 通过 PyInstaller 打包桌面可执行文件（`dist/`）

- `tests/test_parse_inputs.py`
  - 仅覆盖"输入扩展与上传告知"模块的核心路径（不含 pytest 依赖，可直接 `python3` 运行）
  - 用例：extension surface / unsupported / empty / file_not_found / docx happy / OCR 缺失降级 / notifier 事件流 / encrypted pdf parse_error / docx heading_path 注入

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

## 3) Not Implemented / Placeholder

- Flask 服务入口未实现（当前仅 FastAPI 最小入口，标记为可选冗余项）
- API 接口联调待外部接口规范与鉴权信息就绪
- 全量 pytest 自动化测试套件未建立；当前为 **6 份 stdlib-only 测试脚本**（可直接 `python3 tests/<name>.py` 运行）：
  `test_parse_inputs.py` / `test_stage1_core.py` / `test_topic_coarse_classify.py` /
  `test_phase2_features.py` / `test_phase3_non_api.py` / `test_api_service_entry.py`
  合计 **70 条用例 + 1 条 FastAPI 入口断言**（fastapi 缺失时最后一条自动 SKIP，pypdf 缺失时 parse_inputs 最多 SKIP 2 条）
- `service/simple_ui.py` 的 HTTP 层无自动化断言测试，仅在会话内用 curl 做端到端验证；生产级自动化需引入 pytest + httpx 或类似栈
- 图片 OCR 在默认环境下**不真正执行**（需安装 `requirements-ocr.txt` + `tesseract` 系统二进制）；默认行为是结构化降级，而非"已实现完整 OCR"。容器内（`Dockerfile`）默认可用
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
