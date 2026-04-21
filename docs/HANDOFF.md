# HANDOFF

Last Updated: 2026-04-21（基于 4/20 初版落地 + 4/21 交付面板收尾的最终基线）

## 当前可用交接结论

- 仓库 `main` 与 `origin/main` 同步至 `7d2fd23`，本地工作树 clean。
- MVP 主流程端到端可跑并产出 `result.json` / `result.md`（多源时含 `> 本笔记由 N 份文档合并整理` 引用头 + 每条 `*（来源：xxx）*` 斜体标注）。
- 4 种交付面板（CLI / FastAPI / Web UI / Docker）共享同一个 `app.run_pipeline`，CLI 验收过的行为在其他面上同样成立。
- 4/21 收尾做了 UI 对外/调试视图分离、专业视觉体系重构、流程感知 Header + 完整 API 设置覆盖、桌面一键启动与打包。功能无分叉，全部仍复用 `app.run_pipeline`。

## 4/20 落地的 9 个 commit（从老到新）

```
211fd5a  feat: scaffold KnowledgeHarness MVP pipeline
e6aecb0  docs: solidify project constraints state and session rules
fd22d96  fix: align MVP pipeline to truth and establish acceptance framework
bf0dd4f  feat: input expansion + user ingestion notice module
7600326  feat: topic coarse classifier + companion MVP layers
9d0827f  feat: FastAPI + local Web UI + Word export (with hard-earned UI fixes)
3f9a744  refactor(export): clean up final notes layout (md + docx)
1993ba6  feat(ui): uploaded-file pool + upload safety caps
2395953  feat(ui): pool type/count breakdown + output-dir transparency
```

## 4/21 追加的 4 个 commit（从老到新）

```
af81467  docs: sync governance docs with today's delivery baseline
5127194  feat(ui): professional redesign (prod/lab split, tokens, typography)
b58fa67  feat(ui): flow-aware header + full API settings coverage
7d2fd23  feat(ui): split prod/lab views and add desktop launch packaging
```

## 已交付能力（按交付顺序而不是类别排列）

1. **输入扩展 & ingestion notice**（bf0dd4f）：txt/md/pdf/docx 默认可用，图片 opt-in OCR + 显式降级；`failed_sources` 带 `reason`；`ingestion_summary` 自报。
2. **Topic 粗分类层**（7600326）：document 级，本地 taxonomy 约束，`auto/local/api` 三模式，API 越界/失败自动降级；配套 web_enrichment、semantic_conflicts、runtime_config、markdown 折叠、Docker、多个测试脚本。
3. **FastAPI + Local UI + Word 导出**（9d0827f）：三条新交付面板落地；UI 一次审计后修了安全/可用性两类问题（见下）；内嵌 stdlib 多部分解析器替代已废弃的 `cgi`。
4. **最终笔记排版清洗**（3f9a744）：`_render_final_notes_markdown` 去冠词前缀与 heading_path 尾巴；多源自动加引用头与来源标注；"重点速记"自适应（≤12 条时省略）；`export_word` 支持斜体、Quote、水平线。
5. **UI 文件池 + 上传安全限额**（1993ba6）：`uploads/ui_uploads/` 显式成"池"，勾选即可再次运行；新增 `/uploads/clear`、`/uploads/remove`；图片/总数/单文件/请求体四重限额；顺手修了 `collect_input_files` 对 EXCLUDED 路径下显式文件的老 bug。
6. **UI 类型汇总 + 输出目录透明化**（2395953）：池顶部总数胶囊 + 类型分布（按计数降序）；每行带类型 pill（图片琥珀色区分）；输出目录以 `ROOT` 为基准解析，UI 实时显示"本次将写入"的绝对路径与下载链接可用性警告。
7. **治理文档同步基线**（af81467）：把 README / PROJECT_STATE / ACCEPTANCE / ARCHITECTURE / HANDOFF / TODO 六份文档同步到 4/20 代码交付的真实状态，新增 export_notes / export_word / simple_ui 的模块级验收条目。
8. **UI 对外/调试视图分离 + 桌面交付链**（7d2fd23）：`/` 为对外生产视图（默认），`/lab` 为调试视图（不主动暴露入口，需 `KH_UI_SHOW_LAB_LINK=1`）；新增 `launch_app.py` 一键启动（端口占用时自动探测）与 `scripts/build_desktop.py` PyInstaller 桌面打包链路。
9. **专业视觉体系重构**（5127194）：统一 CSS token 配色（`--bg/--surface/--text/--accent`），系统字体栈含 CJK fallback，一致圆角（10/6/999），响应式断点（720px），输入框 focus-ring；`<header>` 与上传卡片分层，copy 去"简易界面"自嘲文案；功能零改动，70/70 测试仍绿。
10. **流程感知 Header + 完整 API 设置覆盖**（b58fa67）：主页标题旁 `API 状态` chip（本地模式 / API 已配置；只显 on/off，**永不回显 URL/Key 值**）；`/settings` 分"主设置"与"按模块覆盖"两栏（topic/enrichment 各 URL/KEY/TEMPLATE，默认折叠），每字段配"清空此字段" checkbox，`_write_env_pairs(clears=...)` 把 `.env` 对应行改写为 `KEY=` 形式保留结构，同步重置 `os.environ` 让变更立即生效。

## 硬验收线（已实测，2026-04-21 重跑）

- `python3 app.py samples/demo.md --output-dir outputs --quiet` → `is_valid=True` / warnings=(none)
- `python3 app.py samples/demo.md samples/ingest_demo.docx --output-dir /tmp/kh_final_check --quiet` → `is_valid=True`，主题分到 `machine_learning` + `reinforcement_learning`
- 6 份 stdlib 测试脚本：`29+16+9+11+5+1(SKIP) = 70 passed + 1 SKIP`（`test_api_service_entry.py` 在 fastapi 未装时 SKIP，是设计行为；本机 tesseract 已装时 parse_inputs 的 degrade-path 1 条 SKIP）
- UI 端到端（curl）：`/` 200、`/lab` 200、`/settings` 200（密钥字段 `type=password` + `autocomplete=new-password` + `value=""`，零泄漏）、`/download?name=result.md` 200、`/download?name=../config.json` 400、`/download?name=/etc/passwd` 400；所有路径遍历防御生效
- 运行时 `result.json` 顶层 11 个必需键齐全：`overview / source_documents / topic_classification / categorized_notes / stage_summaries / key_points / web_resources / semantic_conflicts / review_needed / pipeline_notes / validation`

## 剩余未完成（TODO 明面上只剩 2 条）

- `[ ] 提供 Flask 最小服务入口` — **标记为可选冗余**，FastAPI 已覆盖；如真要做，对应 `service/flask_server.py` 可仿 `api_server.py`。
- `[ ] API 接口联调` — **阻塞在外部**：代码侧 schema、fallback、越界拒绝、重试、masked 密钥管理全部就位，等你的真实 API URL 与鉴权信息就能接。

## 建议的下一步（按顺序）

1. **在真实资料目录上演练**：`python3 app.py <your_dir> --topic-mode local`，看 `topic_classification.topic_groups` 是否合理。若主题漂移，扩 `config/topic_taxonomy.json` 的 aliases。
2. **接入 Topic API 或 Web Enrichment API**（需你提供 endpoint）：只要服务端按 `allowed_labels` 或 `required_fields` 约束返回，本地 UI/CLI/FastAPI 三处都自动可用。
3. **二次整理层**：在 topic 粗分类基础上做"每个 topic 下生成子笔记"，这是粗分类为后续铺的下一站。
4. **NLI / 向量式语义冲突检测**：当前启发式先用着，后续可加深度路径但保留启发式作为快速筛。
5. **UI 端 HTTP-层自动化测试**：引入 `httpx`（或 stdlib 的 `http.client`）+ 一个简单的 `tests/test_simple_ui.py`，把本次用 curl 验过的 8 个场景固化成断言。

## 交接注意事项

- 开发前必须先读：`README.md`、`SKILL.md`、`docs/PROJECT_STATE.md`、`docs/ACCEPTANCE.md`。
- 文档权威顺序见 `docs/ACCEPTANCE.md` §1；冲突时 `docs/PROJECT_STATE.md` 为事实基线。
- 不要把占位能力写成已实现；**图片 OCR 必须保留 opt-in + 降级语义**；**Topic API / Web Enrichment API 仅为可选协助**，本地约束是唯一权威。
- `review_needed` 只承载 chunk 级问题；validation / topic / enrichment / conflict / "no usable input text" 等系统级信号都走 `pipeline_notes`。
- `samples/demo.md` 的 `validation.is_valid == True` 是硬验收线。
- UI 安全守则（来自 `docs/ACCEPTANCE.md` §4 `simple_ui.py`）：
  - 任何 API 密钥值**永远不回显**到 HTML
  - `/download` 严格白名单在 `outputs/` 根目录
  - 上传四重限额不得被绕过

## 本轮交付对依赖栈的影响

| 依赖 | requirements 文件 | 性质 |
|------|-------------------|------|
| `pypdf>=4.2.0` | `requirements.txt` | 核心 |
| `python-docx>=1.1.0` | `requirements.txt` | 核心（.docx 读入 + .docx 导出共享） |
| `pytesseract>=0.3.10` | `requirements-ocr.txt` | Opt-in OCR |
| `Pillow>=10.0.0` | `requirements-ocr.txt` | Opt-in OCR |
| `tesseract-ocr` + `tesseract-ocr-chi-sim` | **OS package** | Opt-in OCR（或直接用 `Dockerfile`） |
| `fastapi>=0.111.0` | `requirements-api.txt` | Opt-in API 服务 |
| `uvicorn>=0.30.0` | `requirements-api.txt` | Opt-in API 服务 |
| 无新增 | — | Topic / Web enrichment / Conflict / UI / Word export 全部用 stdlib |
