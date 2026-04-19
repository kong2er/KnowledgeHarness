# TODO (Priority Ordered)

## P0

- [ ] 建立最小自动化测试（`parse_inputs/chunk_notes/classify_notes/validate_result`）
- [ ] 为 `app.py` 增加失败场景回归用例（空输入、仅失败输入）
- [ ] 明确并固化分类阈值规则，降低 `unclassified` 误伤

## P1

- [ ] 接入可开关的最小 web enrichment（保留 title/url/purpose/reason）
- [ ] 在 validation 中补“外部资源链接缺失”检查（仅在 web enrichment 启用时）
- [ ] 提升 markdown 导出可读性（不改导出文件名）

## P2

- [ ] 支持图片/OCR输入
- [ ] 提供 FastAPI/Flask 最小服务入口
- [ ] 增加配置文件（阈值、分块长度、分类关键词）
