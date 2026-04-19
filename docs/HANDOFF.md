# HANDOFF

Last Updated: 2026-04-20

## 当前可用交接结论

- MVP 主流程已能端到端执行并产出 `result.json` / `result.md`。
- `samples/demo.md` 在当前规则集下 `validation.is_valid == True`，无 warnings。
- 所有 P0 项已关闭（包括分类器阈值修正、导出器完整渲染、review/pipeline_notes 分离、failed/empty 源追踪、单句字符硬切兜底）。
- 下一阶段应先做最小可靠性（测试骨架 + 失败场景回归），再扩展 enrichment / 冲突检测。

## 建议的下一步（按顺序）

1. 建立 `tests/` 最小用例：`parse_inputs` / `chunk_notes` / `classify_notes` / `validate_result` / `export_notes` 各一例；smoke test 串起 `app.run_pipeline` 对 `samples/demo.md`。
2. 接入最小 web enrichment（可开关），确保 `title / url / purpose / relevance_reason` 字段齐全，并在 validation 中补"缺少链接"检查。
3. 实现关键词级冲突检测（最小可用版本），为后续语义冲突铺路。
4. 只在测试骨架立好后，再考虑 OCR / API / 配置文件这类 P2 扩展。

## 交接注意事项

- 开发前必须先读：`README.md`、`SKILL.md`、`docs/PROJECT_STATE.md`、`docs/ACCEPTANCE.md`。
- 若文档与代码冲突：先修正其中一方以恢复一致，再继续开发。
- 不要把占位功能写成已实现。
- `review_needed` 只承载 chunk 级问题；validation / 系统级警告必须走 `pipeline_notes`。
- `samples/demo.md` 的 `validation.is_valid` 是硬验收线，变红时必须先修到绿再合入。
