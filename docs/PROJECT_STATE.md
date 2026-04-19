# PROJECT_STATE

Last Updated: 2026-04-20

## 1) Current Project Structure

```text
KnowledgeHarness/
├── .codex/
│   └── session_rules.md
├── .gitignore
├── README.md
├── SKILL.md
├── app.py
├── requirements.txt
├── docs/
│   ├── ACCEPTANCE.md
│   ├── ARCHITECTURE.md
│   ├── HANDOFF.md
│   ├── PROJECT_STATE.md
│   └── TODO.md
├── tools/
│   ├── __init__.py
│   ├── parse_inputs.py
│   ├── chunk_notes.py
│   ├── classify_notes.py
│   ├── stage_summarize.py
│   ├── extract_keypoints.py
│   ├── validate_result.py
│   └── export_notes.py
├── samples/
│   └── demo.md
├── outputs/                    # gitignored; run artifacts only
│   ├── result.json
│   └── result.md
└── project_memory/             # historical chat context, non-authoritative
    ├── 01_readme_baseline.md
    ├── 02_skill_draft.md
    ├── 03_mvp_task_constraints.md
    └── MEMORY_INDEX.md
```

## 2) Implemented Modules

- `tools/parse_inputs.py`
  - txt / md 读取
  - pdf 读取（依赖 `pypdf`，懒加载）
  - 解析失败 → `logs.failed_sources`
  - 解析成功但正文为空 → `logs.empty_extracted_sources`

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

- `tools/stage_summarize.py`
  - `stage_1` / `stage_2` / `stage_3` 始终输出三键

- `tools/extract_keypoints.py`
  - 按 `BUCKET_ORDER`（pitfalls → concepts → methods → examples）+ 同类内 confidence 降序
  - normalize 去重
  - 最多 `max_points`（默认 12）

- `tools/validate_result.py`
  - 未分类比例、空主分类、重复 chunk、阶段总结缺失
  - 消费 `failed_sources` / `empty_sources` 并产出 `failed_sources_present` / `empty_extracted_sources` 警告

- `tools/export_notes.py`
  - `result.json` + `result.md`
  - md 完整渲染 Stage 1（theme distribution）+ Stage 2（每类 count+preview）+ Stage 3（四个子列表）
  - `review_needed` 与 `pipeline_notes` 分区呈现
  - `failed_sources` / `empty_extracted_sources` 仅在非空时显示

- `app.py`
  - CLI 串联全流程
  - 输入支持文件 / 目录 / glob；默认跳过项目元目录
  - `review_needed` 仅含 chunk 级问题；validation warnings 进 `pipeline_notes`
  - CLI 结尾打印 `is_valid` 与 warnings 摘要

## 3) Not Implemented / Placeholder

- Web enrichment 未接入（`web_resources` 固定返回 `[]`）
- 语义冲突检测未实现（当前仅 `validate_result` 做重复检测）
- OCR / 图片输入未实现
- HTTP API 服务层（FastAPI / Flask）未实现
- 自动化测试（pytest）未建立

## 4) Known Issues

1. 规则分类依赖关键词字典，未在字典覆盖的表述仍会进 `unclassified`。
2. `_leading_label` 只识别"短前缀 + 中/英冒号"，纯口语化段落识别率低。
3. Markdown 导出可读性已显著提升，但未做分级目录折叠，长笔记仍显冗长。

## 5) Acceptance Gate

- 所有修改必须通过 `docs/ACCEPTANCE.md` 中的 §3 通用 Gate 和对应模块 §4 条目。
- 硬约束见 `docs/ACCEPTANCE.md` §5 与 `SKILL.md` Prohibitions。

## 6) Truth Alignment Statement

本文件只描述仓库当前真实状态。未实现能力不得写成"已实现"。
若文档与代码冲突：先修正其中一方以恢复一致，再继续开发。
