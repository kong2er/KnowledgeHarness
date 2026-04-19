# PROJECT_STATE

Last Updated: 2026-04-20

## 1) Current Project Structure

```text
StudyWeaver/
├── app.py
├── README.md
├── SKILL.md
├── requirements.txt
├── docs/
│   ├── ARCHITECTURE.md
│   ├── HANDOFF.md
│   ├── PROJECT_STATE.md
│   └── TODO.md
├── .codex/
│   └── session_rules.md
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
├── outputs/
│   ├── result.json
│   └── result.md
└── project_memory/
    ├── 01_readme_baseline.md
    ├── 02_skill_draft.md
    ├── 03_mvp_task_constraints.md
    └── MEMORY_INDEX.md
```

## 2) Implemented Modules

- `tools/parse_inputs.py`
  - txt/md 读取
  - pdf 读取（依赖 `pypdf`，懒加载）
  - 解析失败记录到 `logs.failed_sources`

- `tools/chunk_notes.py`
  - 按空行分段
  - 超长段按句切分
  - 保留来源元数据并生成 `chunk_id`

- `tools/classify_notes.py`
  - 基于关键词的规则分类
  - 低置信度/歧义进入 `unclassified` + `review_needed`

- `tools/stage_summarize.py`
  - 输出 `stage_1` / `stage_2` / `stage_3`

- `tools/extract_keypoints.py`
  - 聚合并去重 key points

- `tools/validate_result.py`
  - 检查未分类比例
  - 检查空主分类
  - 检查重复 chunk
  - 检查阶段总结是否缺失

- `tools/export_notes.py`
  - 导出 `result.json` 和 `result.md`

- `app.py`
  - 串联全流程（CLI）
  - 支持文件/目录/glob 输入

## 3) Not Implemented / Placeholder

- Web enrichment 未接入（当前固定 `web_resources = []`）
- 冲突检测仅有“重复检查”，无语义冲突检测器
- OCR/图片输入未实现
- API 服务层（Flask/FastAPI）未实现
- 自动化测试（pytest）未建立

## 4) Known Issues

1. 规则分类较弱，容易把真实内容归入 `unclassified`。
2. `extended_reading` 命中规则较粗糙，易漏判。
3. `result.md` 为基础渲染，格式可读性一般。
4. 当前未对“外部资源缺失链接”做运行时校验（因为外部模块尚未接入）。

## 5) Truth Alignment Statement

本文件只描述仓库当前真实状态。未实现能力不得写成“已实现”。
