# HANDOFF

Last Updated: 2026-04-22（含 UI 双栏信息架构重构与 Agent UI 合约文档）

## 交接结论

- 仓库以当前 `main` HEAD 为准，交接前需确认 `main...origin/main` 同步且工作树 clean
- 4 种交付面板（CLI / FastAPI / Web UI / Docker）共享同一个 `app.run_pipeline`
- `samples/demo.md` 上 `is_valid=True` / warnings=(none) 是硬验收线
- TODO 为分级 backlog（P0/P1/P2），其中 P0 仍含 API 真实联调（外部阻塞）
- 全局能力/缺陷/路线总览已抽离到 `docs/ENGINEERING_REVIEW.md`

## 近期关键变更（已纳入主干）

- 新增 `tools/pipeline_runtime.py` 作为共享运行时解析层：统一 `.env` 加载、API 配置探针、runtime config + 覆盖参数解析
- CLI/FastAPI/Flask/UI 全入口改为复用 `build_pipeline_run_kwargs`，确保已实现功能在多入口下默认行为一致
- Flask 请求解析修复：字符串布尔值显式转换（`"false"` 不再被 `bool("false")` 误判）
- `service/simple_ui.py` 启动修复：端口冲突时自动回退后续可用端口，并打印实际启动地址（支持 `--max-port-tries`）
- `launch_app.py` 改为复用 `load_local_env`，修复旧符号引用风险
- 新增 `tests/test_ui_server_port_fallback.py`，覆盖端口回退与 no-fallback 抛错语义
- API 协助范围补齐：`classify_notes` 新增低置信度/未分类 chunk 的受约束 API 补判；`stage_summarize` 新增 Stage 3 可选 API 整理（均保留失败降级）
- `.env.example` 与 `docs/API_SETUP.md` 新增 `CONTENT_CLASSIFIER_*` / `NOTES_ORGANIZER_*` 变量说明
- 图片读取增强：`parse_inputs` 增加“本地 OCR 优先 + API OCR 可选补偿”链路（仅显式启用 API 协助时触发）
- 新增图片 OCR API 配置：`IMAGE_OCR_*` + `image_ocr` payload template
- `ingestion_summary` 增加图片 API 统计字段：`image_api_assist_enabled / image_api_attempted / image_api_succeeded`
- `/settings` 已从“纵向卡片 + 独立清空复选框”重构为“顶部状态栏 + 主从档案区 + 输入框内联清空”
- 新增：字段复制、密钥显隐、toast 反馈、危险操作二次确认
- 语义保持不变：密钥仍不回显；`KEY__clear -> _write_env_pairs(clears=...) -> .env KEY=` 仍是唯一清空路径
- API 协助链路增强：`topic/web` 新增 `openai_compatible` 协议解析，`auto` 可识别 DeepSeek/OpenAI 风格地址并自动补全 chat-completions endpoint
- `app.run_pipeline` API 协助策略更新为“默认关闭、显式开启”：配置 API 不会自动触发调用
- `tools/web_enrichment.py` URL 归一化去除无效转义（打包时不再出现 `invalid escape sequence` 告警）
- `tests/test_phase2_features.py` 新增“URL 末尾标点清洗”断言，防止回归
- 新增 `scripts/run_acceptance_gate.sh`，把测试+demo+结果契约检查收敛为单命令门禁
- `validate_result` 新增 `validation_profile`（`strict/lenient`）并通过 runtime config + CLI/API 入口统一透传
- 新增 `tests/test_simple_ui.py`，覆盖 settings 密钥不回显、下载白名单、输入类 400、上传限额、流水线异常 500（受限环境 SKIP 语义）
- 图片 OCR API 协助新增三档策略：`fallback_only / auto / prefer_api`；`auto` 模式支持本地与 API OCR 结果择优覆盖
- `ingestion_summary` 新增 `image_api_enhance_mode / image_api_enhanced`，便于审计图片增强是否真正生效
- UI 运行页补充“校验策略 strict/lenient”与“图片增强策略”提示，处理摘要新增图片 API 统计（尝试/生效/增强）
- UI 主页面重构为“左操作区 / 右状态与结果区”：主按钮层级突出，状态/结果分区固定，降低首屏认知负担
- 文件导入区新增“选择文件夹”入口，保留历史文件池勾选复用与次级治理动作
- 新增 `GET /outputs`（及 `/lab/outputs`）输出目录浏览页，形成“运行完成 -> 找到结果”闭环（下载仍受 `/download` 白名单约束）
- 新增 UI/Agent 专用治理文档：
  - `docs/UI_LAYOUT_SPEC.md`
  - `docs/AGENT_A_UI_CONTRACT.md`
  - `docs/AGENT_B_UI_INFORMATION_ARCHITECTURE.md`
  - `docs/AGENT_C_UI_USABILITY_ACCEPTANCE.md`
- Windows 封包追踪已固化：`dist/KnowledgeHarness.exe` 与 `dist/KnowledgeHarness.exe.buildinfo.json` 同步维护，可通过 `sha256sum` 快速校验

## Commit Trace

- 历史提交请以 `git log --oneline` 为权威来源，避免手写 ledger 过期。
- 交接文档仅保留“工程结论与下一步”，不重复维护完整 commit 清单。

## 硬验收线（2026-04-22 实测）

| 检查项 | 结果 |
|--------|------|
| `python3 app.py samples/demo.md --output-dir outputs --quiet` | `is_valid=True` / warnings=(none) |
| 混合输入 `demo.md + ingest_demo.docx` | `is_valid=True`，topics 分到 `machine_learning` + `reinforcement_learning` |
| 9 份 stdlib 测试 | gate 通过（含可选依赖 SKIP 语义；受限环境下个别用例可 SKIP） |
| UI 路由 smoke | `/` `/lab` `/settings` `/outputs` 200；`/download` 白名单 200/400/400 |
| UI 密钥泄漏审计 | `type=password` + `autocomplete=new-password` + `value=""`，零泄漏 |
| `result.json` 顶层键 | 11 个必需键齐全 |
| `dist/KnowledgeHarness.exe` | 已更新并入库；SHA256=`15c035f4efadb7c361c5ca0cf27e8445f7eace6a4b0c21511232fd02ad5710a9` |

## 依赖栈

| 依赖 | 归属 | 性质 |
|------|------|------|
| `pypdf>=4.2.0` | `requirements.txt` | 核心（PDF 解析） |
| `python-docx>=1.1.0` | `requirements.txt` | 核心（docx 读入 + 导出共享） |
| `pytesseract>=0.3.10` + `Pillow>=10.0.0` | `requirements-ocr.txt` | Opt-in OCR |
| `tesseract-ocr` + `tesseract-ocr-chi-sim` | OS package | Opt-in OCR |
| `fastapi>=0.111.0` + `uvicorn>=0.30.0` | `requirements-api.txt` | Opt-in API 服务 |
| `flask>=3.0.0` | `requirements-flask.txt` | Opt-in API 服务（Flask 入口） |
| `pyinstaller` | `requirements-desktop.txt` | Opt-in 桌面打包 |
| — | — | Topic / Web enrichment / Conflict / UI / Word 导出 全部 stdlib |

## 建议的下一步（按顺序）

1. **真实资料演练**：`python3 app.py <your_dir> --topic-mode local`，按 `topic_groups` 调 `config/topic_taxonomy.json` aliases
2. **接入真实 API**：服务端按 `allowed_labels` / `required_fields` 返回即可，CLI/UI/FastAPI 三处自动联动
3. **二次整理层**：在主题粗分类之上生成"每 topic 子笔记"
4. **NLI / 向量语义冲突**：保留启发式作为快速筛
5. **API 真实联调验收**：待外部 endpoint/鉴权策略就绪后完成连通、错误码与限流策略验证

## 交接注意事项

- 开发前必读：`README.md` → `SKILL.md` → `docs/PROJECT_STATE.md` → `docs/ACCEPTANCE.md`
- 冲突时权威顺序：`PROJECT_STATE` > `SKILL`/`ACCEPTANCE` > `ARCHITECTURE`/`README` > `project_memory/*`
- 不要把占位能力写成已实现；**图片 OCR 保留 opt-in + 降级语义**；**Topic/Web API 仅为可选协助**
- `review_needed` 只装 chunk 级问题；validation / topic / enrichment / conflict / "no usable input text" 等系统级信号走 `pipeline_notes`
- **UI 安全守则**（`docs/ACCEPTANCE.md` §4 `simple_ui.py`）：
  - 任何 API 密钥值**永远不回显**到 HTML
  - `/download` 严格白名单在 `outputs/` 根目录
  - 上传四重限额不得被绕过
