# KnowledgeHarness

KnowledgeHarness 是一个面向学习资料整理的工程化流水线工具，目标是把分散资料转换为可复习的结构化笔记。

## 项目定位

- 用户资料优先（本地输入是主数据源）
- 流程化处理，不走一次性"聊天式总结"
- 输出带来源信息、带校验结果
- 当前实现为 **CLI MVP**，优先验证流程闭环

## 治理文档（Harness Engineering 视角）

| 文件 | 作用 |
|------|------|
| `SKILL.md` | Agent 行为规范（先分类后总结、不编造、占位能力的如实描述） |
| `docs/PROJECT_STATE.md` | 仓库真实状态（已实现 / 未实现 / 已知问题） |
| `docs/ARCHITECTURE.md` | 模块与数据契约 |
| `docs/ACCEPTANCE.md` | 模块级与通用 Gate 的验收条件 |
| `docs/HANDOFF.md` | 当前版本交接结论 |
| `docs/API_SETUP.md` | API 接入最小说明（环境变量 + 请求格式） |
| `docs/TODO.md` | 已登记未完成事项 |
| `.codex/session_rules.md` | 会话级前置门禁 |
| `project_memory/` | 历史对话副本，非权威 |

## 当前支持能力（已实现）

1. 输入解析
   - 默认支持：`.txt` / `.md` / `.pdf` / `.docx`（`python-docx`）
   - docx 样式感知：抽取 heading 层级并以内联 `heading_path` 注入正文，帮助后续分类
   - **Opt-in OCR**：`.png` / `.jpg` / `.jpeg` 需额外安装 `requirements-ocr.txt` 与 `tesseract` 系统二进制；未安装时不伪装成功，而是记录 `failed_sources[*].reason == "ocr_backend_unavailable"`
   - 解析失败源 → `logs.failed_sources`（带 `reason`：`unsupported_file_type` / `file_not_found` / `parse_error` / `ocr_backend_unavailable`）
   - 解析成功但正文空 → `logs.empty_extracted_sources`
   - `overview.ingestion_summary`：运行期自报"本次真实可用扩展集 + OCR 后端状态"
2. 文本切分：按段落 → 句子 → 字符三级 fallback，保证不超 `max_chars`
3. **主题粗分类层（Topic Coarse Classification）**：
   - 文档级粗分类（source/document 粒度），不替代 chunk 级分类
   - 标签来自本地约束集合：`config/topic_taxonomy.json`
   - 支持 `--topic-mode auto|local|api`（默认 `auto`）
   - API 为可选协助；任何异常都会降级（`unknown_topic` / local rule），不中断主流程
4. 规则分类（关键词 + 起始标签双路打分，tie-break 走 `CATEGORY_PRIORITY`）：
   - `basic_concepts`
   - `methods_and_processes`
   - `examples_and_applications`
   - `difficult_or_error_prone_points`
   - `extended_reading`
   - `unclassified`
5. 三阶段总结：`stage_1 / stage_2 / stage_3`
6. 重点提炼：按类别优先级 + 置信度降序聚合并去重
   - 支持可选阈值：`--keypoint-min-confidence`
7. 可开关 Web Enrichment：
   - `--enable-web-enrichment --web-enrichment-mode off|local|api|auto`
   - `local` 模式从用户资料中提取 URL；`api`/`auto` 支持外部协助并失败降级
   - 输出严格保留：`title / url / purpose / relevance_reason`
8. 语义冲突检测（最小规则版）：
   - 在 chunk 级声明中检测互斥主张（如“必须/不需要”、“可以/不可以”）
   - 结果写入 `semantic_conflicts` 并进入 validation/pipeline notes
9. 结果校验：未分类比例、空主分类、重复内容、阶段总结缺失、failed/empty 源提示、web 资源字段缺失（启用 enrichment 时）、语义冲突告警
10. 导出：`outputs/result.json` + `outputs/result.md`（Stage 1/2/3 完整渲染 + Ingestion Summary + Topic Overview + Semantic Conflicts）
11. 运行时配置与交付增强：
   - 支持 `config/pipeline_config.json`（分块长度、关键词规则、OCR 语言、导出折叠等）
   - 支持 Markdown 折叠导出（`export.markdown_use_details`）
   - 提供 OCR-ready Docker 交付基础（`Dockerfile`）
12. 最小服务入口（FastAPI）：
   - 提供 `service/api_server.py`（`/health`、`/pipeline/run`、`/pipeline/capabilities`）
   - 服务层复用现有 `run_pipeline`，保持同样降级语义

## 当前未实现或占位（必须知晓）

- **图片 OCR 是 opt-in**：默认环境下图片输入会优雅降级为 `ocr_backend_unavailable`；仅在安装 `requirements-ocr.txt` 并具备 `tesseract` 二进制时才真正 OCR
- Flask 服务入口未实现（当前仅 FastAPI 最小入口）
- 主题粗分类的远程 API 仅提供可选接入点，默认不依赖外部服务
- 自动化测试：已提供多份 stdlib 测试脚本（`tests/test_parse_inputs.py` / `tests/test_stage1_core.py` / `tests/test_topic_coarse_classify.py` / `tests/test_phase2_features.py` / `tests/test_phase3_non_api.py` / `tests/test_api_service_entry.py`），尚未建立 pytest 套件

## 运行方式

1. 安装依赖（核心）：

```bash
pip install -r requirements.txt
```

2.（可选）启用图片 OCR：

```bash
pip install -r requirements-ocr.txt
# 系统层（Debian/Ubuntu）
sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
```

3.（可选）接入 API（主题粗分类 / web enrichment）：

```bash
cp .env.example .env
# 编辑 .env，填入 TOPIC_CLASSIFIER_API_URL / WEB_ENRICHMENT_API_URL 等
```

默认 API 请求格式模板：
- `config/api_payload_templates.json`
- 未配置 API 时，CLI 会提示：`请接入API后使用`
- 推荐在 `.env` 配置统一 API：`KNOWLEDGEHARNESS_API_URL` / `KNOWLEDGEHARNESS_API_KEY`

4. 执行（单文件 / 目录 / 通配符均可；项目元目录会被自动跳过）：

```bash
python3 app.py samples/demo.md --output-dir outputs
# 指定运行时配置
python3 app.py samples/demo.md --output-dir outputs --config config/pipeline_config.json
# 多类型混合输入
python3 app.py samples/ --output-dir outputs
# 强制仅本地主题粗分类（禁用 API 协助）
python3 app.py samples/ --output-dir outputs --topic-mode local
# 使用自定义 topic taxonomy
python3 app.py samples/ --output-dir outputs --topic-taxonomy config/topic_taxonomy.json
# 启用最小 web enrichment（本地 URL 提取模式）
python3 app.py samples/ --output-dir outputs --enable-web-enrichment --web-enrichment-mode local
# 只保留置信度>=0.6 的 key points
python3 app.py samples/ --output-dir outputs --keypoint-min-confidence 0.6
# 同时导出 Word（.docx）
python3 app.py samples/ --output-dir outputs --export-docx
# 导出完整报告（含阶段与校验信息），默认是“纯笔记版”
python3 app.py samples/ --output-dir outputs --full-report
# 静默（不输出 [ingest] 进度）
python3 app.py samples/ --output-dir outputs --quiet
```

5. 查看结果：

- `outputs/result.json`
- `outputs/result.md`
- 默认 `result.md` 为“最终整理笔记”；流程诊断信息保留在 `result.json`

6. 运行本模块的最小测试（不依赖 pytest）：

```bash
python3 tests/test_parse_inputs.py
python3 tests/test_stage1_core.py
python3 tests/test_topic_coarse_classify.py
python3 tests/test_phase2_features.py
python3 tests/test_phase3_non_api.py
python3 tests/test_api_service_entry.py
```

7. 启动 FastAPI 最小服务（可选）：

```bash
pip install -r requirements-api.txt
uvicorn service.api_server:app --host 0.0.0.0 --port 8000 --reload
```

8. 启动最简本地 Web UI（可选，**零第三方依赖**）：

```bash
python3 service/simple_ui.py --host 127.0.0.1 --port 8765
# 浏览器打开 http://127.0.0.1:8765
```

UI 功能一览：
- **文件上传** + **文件池**：上传的文件保留在 `uploads/ui_uploads/`，页面会列出池内所有文件（含类型 pill / 大小 / 时间），下次运行直接勾选即可，不用重传。单次运行上限：**图片 10 张 / 总数 20 个 / 单文件 20 MB / 整个请求体 200 MB**（常量在 `service/simple_ui.py` 顶部可调）。
- **输出目录可自设**：相对路径以项目根为基准；UI 实时显示"本次将写入"的绝对路径。当目标不在 `outputs/` 根目录时，下载链接自动退化为纯文本路径并给出警告。
- **下载端点** `GET /download?name=result.md|result.json|result.docx`：严格限制在 `outputs/` 根目录，路径遍历被双层校验拦截。
- **API 设置页** `/settings`：只展示 `已配置（末 4 位：···abcd）` 这种 masked 状态，**永不回显密钥原值**；输入框为 `type=password` + `autocomplete=new-password`；留空提交 = 保持原值。
- **进度反馈**：submit 时禁用按钮并显示"处理中…"状态条，避免用户误以为页面卡住。
- **错误分级**：400（输入错误：空选 / 超限 / 不支持格式）和 500（流水线异常）都保留 UI 存活，不白屏。

9. Docker 运行（OCR-ready）：

```bash
docker build -t knowledgeharness .
docker run --rm -v "$PWD/samples:/data" knowledgeharness \
  python app.py /data/demo.md --output-dir /data/out
```

## 输出结构契约

- `overview`：`source_count` / `chunk_count` / `failed_sources` / `empty_extracted_sources` / `ingestion_summary`
- `source_documents`
- `topic_classification`（document 级 topic label / confidence / reason / fallback_state）
- `categorized_notes` / `stage_summaries` / `key_points`（`stats.min_confidence`）
- `web_resources`（启用 enrichment 时产出）
- `semantic_conflicts`（启发式冲突对）
- `review_needed`（仅 chunk 级问题）
- `pipeline_notes`（系统级警告，如 validation warnings、"no usable input text"）
- `validation`（`is_valid` + `warnings` + `stats`）

## MVP 边界

- 先保证流程清晰、模块可独立测试
- 不追求模型能力或复杂 UI
- 不把占位能力描述成已上线能力
- 任何扩展（联网、OCR、API）需在 `docs/TODO.md` 明确列入并按 `docs/ACCEPTANCE.md` 验收后再标记"已完成"
