# Final Status Snapshot (2026-04-21)

> 非权威快照：用于快速回忆本次交付结果。事实以 `docs/PROJECT_STATE.md` 为准。

## 当前完成度（代码已落地）

- 主流水线可用：parse -> chunk -> topic coarse classify -> content classify -> summarize -> key points -> validate -> export。
- 输入支持：`.txt/.md/.pdf/.docx` 默认可用，图片 OCR 为 opt-in（依赖缺失时降级）。
- 双分类层已分离：
  - 主题粗分类（document/source 粒度，受 taxonomy 约束）
  - 内容功能分类（chunk 粒度，概念/方法/例子/易错/扩展/未分类）
- 导出支持：`result.json` + `result.md`，可选 `result.docx`。
- 服务入口：CLI + FastAPI + Flask + 本地 UI + Docker（同一 `run_pipeline`）。

## 本轮关键修复

- 修复 `tests/test_api_service_entry.py` 与 `tests/test_flask_service_entry.py` 的脚本执行导入路径问题（`service` 包可稳定导入）。
- 对齐文档与真实代码状态（Flask 入口已实现，不再标注“未实现”）。
- UI `/lab` 默认禁用，需 `KH_UI_ENABLE_LAB=1` 才可访问；首页入口还需 `KH_UI_SHOW_LAB_LINK=1`。

## 已验证结果（本地）

- `python3 app.py samples/demo.md --output-dir outputs --quiet`：`is_valid=True`，warnings 空。
- `tests/test_*.py`：全部通过；FastAPI 入口测试在未安装 fastapi 时按设计 SKIP。

## 剩余阻塞（未完成但非代码缺陷）

- 真实 API 联调仍依赖外部接口参数（URL、鉴权、响应契约）。
- 当前代码侧已具备：模板、约束、fallback、warnings 汇总、UI 设置入口与提示“请接入API后使用”。

