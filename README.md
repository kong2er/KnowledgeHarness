# KnowledgeHarness

把分散的学习资料（txt / md / pdf / docx / 图片）整理成结构化复习笔记的流水线工具。

## 核心定位

- **用户资料优先**：本地输入是主数据源，外部补充仅作可选协助
- **流程化处理**：分类 → 总结 → 提炼 → 校验 → 导出，不是一次性"聊天式总结"
- **真实性守则**：占位能力如实降级（图片 OCR 缺依赖 → 显式告知，不伪装成功）
- **同一条流水线 × 5 种调用方式**：CLI / FastAPI / Flask / 本地 Web UI / Docker，行为完全一致

## 能力概览

| 分层 | 说明 |
|------|------|
| 输入 | `.txt / .md / .pdf / .docx` 默认可用；图片 `.png/.jpg/.jpeg` 为 **opt-in OCR**（需额外安装，否则降级为 `ocr_backend_unavailable`） |
| 分类 | 文档级主题粗分类（本地 taxonomy 约束，支持可选 API 协助 + 失败降级）+ chunk 级内容分类（关键词规则 + 起始标签双路打分） |
| 摘要 | 三阶段总结（Stage 1/2/3）+ 基于置信度与类别优先级的重点提炼 |
| 校验 | 未分类比例、重复、阶段缺失、失败源、语义冲突（启发式）、web 资源字段缺失 |
| 导出 | `result.json` + `result.md`（最终笔记版 / 完整报告版可切换）+ 可选 `result.docx` |
| 服务层 | FastAPI + Flask 最小入口 + 本地 Web UI（stdlib 零依赖，含文件池、四重上传限额、masked API 设置、路径遍历防御） |

## 快速开始

```bash
# 1. 安装核心依赖
pip install -r requirements.txt

# 2. 跑 demo（单文件）
python3 app.py samples/demo.md --output-dir outputs

# 结果：outputs/result.json + outputs/result.md
```

### 三种使用姿势

```bash
# CLI：单文件 / 目录 / 通配符均可
python3 app.py samples/ --output-dir outputs

# 本地 Web UI（零第三方依赖，自动打开浏览器）
python3 launch_app.py
# 或：./start_ui.sh（Linux/macOS）/ start_ui.bat（Windows）
# 调试视图 /lab 默认禁用；如需启用：
# KH_UI_ENABLE_LAB=1 python3 launch_app.py
# （若还要在首页显示入口，再加 KH_UI_SHOW_LAB_LINK=1）

# FastAPI 服务（可选依赖）
pip install -r requirements-api.txt
uvicorn service.api_server:app --port 8000

# Flask 服务（可选依赖）
pip install -r requirements-flask.txt
python3 service/flask_server.py --port 8001
```

### 常用 CLI 开关

```bash
--output-dir <path>              # 输出目录（相对路径以项目根为基准）
--topic-mode auto|local|api      # 主题粗分类模式（默认 auto，API 失败自动降级）
--enable-web-enrichment          # 启用可开关的 web enrichment
--export-docx                    # 额外导出 result.docx
--full-report                    # 完整报告版（默认是纯笔记版）
--quiet                          # 静默，不打印 [ingest] 进度
--config <file>                  # 自定义运行时配置（见 config/pipeline_config.json）
```

## 可选扩展

| 能力 | 如何启用 |
|------|---------|
| 图片 OCR | `pip install -r requirements-ocr.txt` + 系统装 `tesseract-ocr`（或直接用 `Dockerfile`） |
| API 协助（主题 / web enrichment） | `cp .env.example .env` 并填入 `KNOWLEDGEHARNESS_API_URL`，详见 `docs/API_SETUP.md` |
| 桌面可执行文件 | `pip install -r requirements-desktop.txt && python3 scripts/build_desktop.py` |
| Docker（OCR-ready） | `docker build -t knowledgeharness . && docker run --rm -v "$PWD/samples:/data" knowledgeharness python app.py /data/demo.md --output-dir /data/out` |

## 治理文档索引

| 文件 | 作用 |
|------|------|
| `SKILL.md` | Agent 行为规范（分类先于总结、不编造、占位能力如实降级） |
| `docs/PROJECT_STATE.md` | **事实权威**：已实现 / 未实现 / 已知问题 |
| `docs/ACCEPTANCE.md` | **规则权威**：模块级 + 通用 Gate 验收条件 |
| `docs/ARCHITECTURE.md` | 模块关系与数据契约（顶层 `result` 结构） |
| `docs/HANDOFF.md` | 当前版本交接结论 |
| `docs/API_SETUP.md` | API 接入最小说明 |
| `docs/TODO.md` | 未完成事项（当前仅 2 条，均非阻塞） |
| `.codex/session_rules.md` | 会话级前置门禁 |

**权威顺序（冲突时）**：`PROJECT_STATE` > `SKILL` / `ACCEPTANCE` > `ARCHITECTURE` / `README` > `project_memory/*`（历史副本，非权威）

## 测试

```bash
# 7 份 stdlib 测试脚本（不依赖 pytest），含可选依赖的 SKIP 语义
for t in tests/test_*.py; do python3 "$t"; done
```

## MVP 边界

- 不追求模型能力或复杂 UI
- 图片 OCR 保留 opt-in 语义，不拟改为"默认可用"（容器镜像视为开箱即用形态）
- 高级（NLI / 向量）语义冲突检测、生产级鉴权/限流/队列不在 MVP 范围
- 任何扩展需先登记到 `docs/TODO.md` 并按 `docs/ACCEPTANCE.md` 验收后再标记完成
