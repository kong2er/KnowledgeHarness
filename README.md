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
| `docs/TODO.md` | 已登记未完成事项 |
| `.codex/session_rules.md` | 会话级前置门禁 |
| `project_memory/` | 历史对话副本，非权威 |

## 当前支持能力（已实现）

1. 输入解析：`txt / md / pdf`，失败源进入 `failed_sources`、空抽取源进入 `empty_extracted_sources`
2. 文本切分：按段落 → 句子 → 字符三级 fallback，保证不超 `max_chars`
3. 规则分类（关键词 + 起始标签双路打分，tie-break 走 `CATEGORY_PRIORITY`）：
   - `basic_concepts`
   - `methods_and_processes`
   - `examples_and_applications`
   - `difficult_or_error_prone_points`
   - `extended_reading`
   - `unclassified`
4. 三阶段总结：`stage_1 / stage_2 / stage_3`
5. 重点提炼：按类别优先级 + 置信度降序聚合并去重
6. 结果校验：未分类比例、空主分类、重复内容、阶段总结缺失、failed/empty 源提示
7. 导出：`outputs/result.json` + `outputs/result.md`（Stage 1/2/3 完整渲染）

## 当前未实现或占位（必须知晓）

- Web enrichment 仍是占位：`web_resources = []`，**未接入搜索工具**
- 语义冲突检测未实现（仅做重复检测）
- 图片 / OCR 输入未实现
- API 服务（Flask / FastAPI）未实现
- 自动化测试（pytest）未建立

## 运行方式

1. 安装依赖：

```bash
pip install -r requirements.txt
```

2. 执行（单文件 / 目录 / 通配符均可；项目元目录会被自动跳过）：

```bash
python3 app.py samples/demo.md --output-dir outputs
```

3. 查看结果：

- `outputs/result.json`
- `outputs/result.md`

## 输出结构契约

- `overview` / `source_documents`
- `categorized_notes` / `stage_summaries` / `key_points`
- `web_resources`（占位）
- `review_needed`（仅 chunk 级问题）
- `pipeline_notes`（系统级警告，如 validation warnings）
- `validation`（`is_valid` + `warnings` + `stats`）

## MVP 边界

- 先保证流程清晰、模块可独立测试
- 不追求模型能力或复杂 UI
- 不把占位能力描述成已上线能力
- 任何扩展（联网、OCR、API）需在 `docs/TODO.md` 明确列入并按 `docs/ACCEPTANCE.md` 验收后再标记"已完成"
