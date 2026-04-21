# AGENT_A_UI_CONTRACT

Last Updated: 2026-04-22

Agent A（资料接入与交互可见性 Agent）负责 UI 输入区与真实接入能力的一致性。

## 1. 输入区字段契约

`service/simple_ui.py` 主页面输入区必须对应以下真实字段：

- `upload_files`（文件/文件夹上传，支持多文件）
- `existing_files[]`（文件池复用勾选）
- `output_dir`
- `enable_api_assist`
- `export_docx`
- `validation_profile`
- （调试视图）`enable_web_enrichment` / `topic_mode` / `web_enrichment_mode` / `keypoint_*`

约束：

- UI 不得展示超出后端可解析字段的“假控件”
- 字段默认值必须与 `build_pipeline_run_kwargs` 与主流程一致

## 2. 文件状态枚举（UI 可见层）

文件项状态（用于文件池列表）：

- `pending_select`：待选择
- `selected_for_run`：本次将处理
- `removed`：已从文件池删除

运行后聚合状态（右栏统计）：

- `succeeded_count`
- `failed_count`
- `empty_extracted_count`
- `detected_count`

## 3. 支持类型说明契约

UI 必须如实展示：

- 默认支持：`.txt/.md/.pdf/.docx`
- 图片支持：`.png/.jpg/.jpeg`（OCR 可选能力）

禁止将未实现输入类型写成已支持。

## 4. 失败原因 -> 用户提示语映射

Agent A 维护用户可读映射：

- `unsupported_file_type` -> 当前文件类型暂不支持
- `file_not_found` -> 文件不存在或已被移动
- `parse_error` -> 文件解析失败，请检查文件是否损坏
- `ocr_backend_unavailable` -> OCR 环境未就绪，请安装依赖或改用文本资料
- 空选 -> 未选择任何文件，请先上传或勾选文件池文件
- 超限 -> 文件数量/大小超出单次限制，请减少输入后重试

## 5. 降级与一致性

- 上传失败或单文件拒收时，不中断 UI 主页面渲染
- 输入错误返回 400，保留页面与可操作控件
- 不允许 Agent A 越界改写分类/总结逻辑
