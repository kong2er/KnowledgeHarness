# MVP Task Constraints (Memory Copy)

你现在是这个项目的开发助手。请基于以下项目说明，继续为我生成一个可运行的 MVP 版本代码。

项目名：KnowledgeHarness

目标：
做一个学习资料整理工具，以用户上传资料为主，结合有限网络补充，自动完成：
1. 内容解析
2. 内容切分
3. 自动分类
4. 阶段总结
5. 重点提炼
6. 外部资源补充
7. 结果校验
8. markdown/json 导出

技术要求：
- 使用 Python
- 代码结构清晰，便于后续扩展
- 优先实现命令行版本或最小 Flask/FastAPI 版本
- 先不要做复杂前端
- 重点保证流程清晰，而不是追求花哨界面

请先完成以下内容：
1. 创建项目目录结构
2. 编写 requirements.txt
3. 编写 tools/parse_inputs.py
   - 支持读取 txt / md / pdf
   - 返回统一的数据结构
4. 编写 tools/chunk_notes.py
   - 将文本按段落或规则切分为 chunk
5. 编写 tools/classify_notes.py
   - 基于简单规则或占位逻辑实现分类
   - 分类到 basic_concepts / methods_and_processes / examples_and_applications / difficult_or_error_prone_points / extended_reading / unclassified
6. 编写 tools/stage_summarize.py
   - 生成 3 个阶段的基础总结
7. 编写 tools/extract_keypoints.py
   - 提取重点记要
8. 编写 tools/validate_result.py
   - 检查未分类项、空分类、重复内容
9. 编写 tools/export_notes.py
   - 导出 result.json 和 result.md
10. 编写 app.py
   - 先做一个最小主程序，串联上述流程

约束：
- 用户资料优先，外部资料只是补充
- 分类必须在总结之前
- 如果内容无法可靠分类，必须进入 review_needed
- 输出必须保留来源信息
- 代码里加入必要注释
- 每个模块都尽量可独立测试

输出顺序：
请先给我完整项目目录树，然后依次生成各文件代码。这是我们这次任务的为方便你理解的任务词
