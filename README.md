# KnowledgeHarness

KnowledgeHarness 是一个面向学习资料整理的工程化流水线工具，目标是把分散资料转换为可复习的结构化笔记。

## 项目定位

- 用户资料优先（本地输入是主数据源）
- 流程化处理，不走一次性“聊天式总结”
- 输出带来源信息、带校验结果
- 当前实现为 **CLI MVP**，优先验证流程闭环

## 当前支持能力（已实现）

1. 输入解析：`txt / md / pdf`
2. 文本切分：按段落 + 超长段落按句拆分
3. 规则分类：
   - `basic_concepts`
   - `methods_and_processes`
   - `examples_and_applications`
   - `difficult_or_error_prone_points`
   - `extended_reading`
   - `unclassified`
4. 三阶段总结：`stage_1 / stage_2 / stage_3`
5. 重点提炼：从分类结果抽取 key points
6. 结果校验：未分类比例、空主分类、重复内容、阶段总结缺失
7. 导出：`outputs/result.json` + `outputs/result.md`

## 当前未实现或占位（必须知晓）

- 网络补充模块仍是占位：`web_resources = []`，**未接入搜索工具**
- “冲突内容检测”目前未独立实现（仅做重复检测）
- 图片/OCR 输入未实现
- API 服务（Flask/FastAPI）未实现，当前仅命令行

## 运行方式

1. 安装依赖：

```bash
pip install -r requirements.txt
```

2. 执行（单文件/目录/通配符均可）：

```bash
python3 app.py samples/demo.md --output-dir outputs
```

3. 查看结果：

- `outputs/result.json`
- `outputs/result.md`

## MVP 边界

- 先保证流程清晰、模块可独立测试
- 不追求模型能力或复杂 UI
- 不把占位能力描述成已上线能力
- 任何扩展（联网、OCR、API）需在 `docs/TODO.md` 明确列入并验收后再标记“已完成”
