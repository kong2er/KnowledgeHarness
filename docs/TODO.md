# TODO (Priority Ordered)

## P0

- [x] ~~降低 `classify_notes` 的 `unclassified` 误伤~~（2026-04-20：改为类别优先级 tie-break + 起始标签加成 + 分步 confidence）
- [x] ~~`export_notes` 完整渲染 Stage 1/2/3~~（2026-04-20）
- [x] ~~分离 `review_needed` 与系统级警告（`pipeline_notes`）~~（2026-04-20）
- [x] ~~`validate_result` 消费 `failed_sources` / `empty_sources`~~（2026-04-20）
- [x] ~~`chunk_notes` 单句超 `max_chars` 的字符硬切兜底~~（2026-04-20）
- [x] ~~`collect_input_files` 默认跳过项目元目录~~（2026-04-20）
- [ ] 建立最小自动化测试（`parse_inputs / chunk_notes / classify_notes / validate_result`）
- [ ] 为 `app.py` 增加失败场景回归用例（空输入、仅失败输入、PDF 加密等）

## P1

- [ ] 接入可开关的最小 web enrichment（保留 `title / url / purpose / relevance_reason`）
- [ ] 在 validation 中补"外部资源链接缺失"检查（仅在 web enrichment 启用时）
- [ ] 引入语义冲突检测（至少关键词冲突规则）并接入 validation
- [ ] 按 `confidence` 给 key_points 加可选阈值（避免低 conf 占位挤掉高 conf）

## P2

- [ ] 支持图片 / OCR 输入
- [ ] 提供 FastAPI / Flask 最小服务入口
- [ ] 增加配置文件（阈值、分块长度、分类关键词、LABEL_HINTS）
- [ ] Markdown 导出支持分级目录折叠，提高长笔记可读性
