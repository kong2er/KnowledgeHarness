# API_SETUP

Last Updated: 2026-04-22

本文件只说明当前仓库已实现的最基础 API 接入方式。

## 1. 当前支持的 API 接入点

- Topic Coarse Classifier API（`tools/topic_coarse_classify.py`）
- Content-Type Classifier API（`tools/classify_notes.py`，用于低置信度/未分类 chunk 的受约束补判）
- Notes Organizer API（`tools/stage_summarize.py`，用于 Stage 3 的受约束整理）
- Image OCR API（`tools/parse_inputs.py`，用于图片在本地 OCR 不可用/效果弱时的可选提取增强）
- Web Enrichment API（`tools/web_enrichment.py`）

两者都是可选协助模式。
未接入 API 时，系统会自动降级，不会中断主流程。

另外，仓库已提供最小服务入口：
- FastAPI：`service/api_server.py`
- Flask：`service/flask_server.py`

## 2. 环境配置

1. 复制模板：

```bash
cp .env.example .env
```

2. 填写 `.env`（推荐使用统一 API 配置）：

```dotenv
KNOWLEDGEHARNESS_API_URL=https://your-shared-api.example.com/infer
KNOWLEDGEHARNESS_API_KEY=your_token_if_needed
# 可选：custom | openai_compatible | auto（默认 auto）
KNOWLEDGEHARNESS_API_STYLE=auto
# 可选：openai_compatible 默认模型
KNOWLEDGEHARNESS_API_MODEL=deepseek-chat
```

说明：
- `app.py` 会自动读取项目根目录 `.env`。
- 若你在系统环境中已设置同名变量，`.env` 不会覆盖已有值。
- 当用户选择 `--topic-mode api` 或 `--web-enrichment-mode api` 但 URL 未配置时，CLI 会提示：`请接入API后使用`。
- 如需按模块覆盖，可额外设置：
  - `TOPIC_CLASSIFIER_API_URL` / `TOPIC_CLASSIFIER_API_KEY`
  - `TOPIC_CLASSIFIER_API_STYLE` / `TOPIC_CLASSIFIER_API_MODEL`
  - `IMAGE_OCR_API_URL` / `IMAGE_OCR_API_KEY`
  - `IMAGE_OCR_API_STYLE` / `IMAGE_OCR_API_MODEL`
  - `IMAGE_OCR_ENHANCE_MODE` / `IMAGE_OCR_ENHANCE_MIN_SCORE`
  - `IMAGE_OCR_ENHANCE_RATIO` / `IMAGE_OCR_ENHANCE_MIN_DELTA`
  - `CONTENT_CLASSIFIER_API_URL` / `CONTENT_CLASSIFIER_API_KEY`
  - `CONTENT_CLASSIFIER_API_STYLE` / `CONTENT_CLASSIFIER_API_MODEL`
  - `NOTES_ORGANIZER_API_URL` / `NOTES_ORGANIZER_API_KEY`
  - `NOTES_ORGANIZER_API_STYLE` / `NOTES_ORGANIZER_API_MODEL`
  - `IMAGE_OCR_API_URL` / `IMAGE_OCR_API_KEY`
  - `IMAGE_OCR_API_STYLE` / `IMAGE_OCR_API_MODEL`
  - `WEB_ENRICHMENT_API_URL` / `WEB_ENRICHMENT_API_KEY`
  - `WEB_ENRICHMENT_API_STYLE` / `WEB_ENRICHMENT_API_MODEL`
  - 覆盖变量留空时自动回退统一配置。

### 2.1 OpenAI/DeepSeek 兼容模式（新增）

- 当 `*_API_STYLE=auto` 且 URL 类似 `https://api.deepseek.com` / `https://api.openai.com`（或仅主域名）时，
  系统会自动按 openai-compatible 协议调用。
- endpoint 自动补全规则：
  - `https://api.deepseek.com` -> `https://api.deepseek.com/v1/chat/completions`
  - `https://api.deepseek.com/v1` -> `.../v1/chat/completions`
  - 已填完整 `.../chat/completions` 则保持不变
- 仍保留 `custom` 协议：如果你的服务是项目原生 JSON schema，可设 `*_API_STYLE=custom`。

## 3. 默认请求格式文件

默认模板文件：

- `config/api_payload_templates.json`

它定义了两类模板：
- `topic_classifier.system_prompt` + `output_contract`
- `content_classifier.system_prompt` + `output_contract`
- `notes_organizer.system_prompt` + `output_contract`
- `image_ocr.system_prompt` + `output_contract`
- `web_enrichment.system_prompt` + `output_contract`

可通过环境变量替换模板路径：
- `TOPIC_CLASSIFIER_API_TEMPLATE`
- `IMAGE_OCR_API_TEMPLATE`
- `CONTENT_CLASSIFIER_API_TEMPLATE`
- `NOTES_ORGANIZER_API_TEMPLATE`
- `IMAGE_OCR_API_TEMPLATE`
- `WEB_ENRICHMENT_API_TEMPLATE`

## 3.1 UI 多 API 档案（新增）

`/settings` 页面支持：

- 保存“当前 API 环境配置”为档案（可保存多套）
- 选择某个档案并统一查看详情（URL/模板路径可见，密钥仅掩码显示）
- 档案字段覆盖统一 API + Topic + Image OCR + Content Classifier + Notes Organizer + Web Enrichment
- 应用某个档案到当前环境（可选：同时设为默认）
- 用“当前环境配置”覆盖某个已存在档案（用于修改档案）
- 删除某个档案
- 一键清空当前全部 API 环境配置

档案存储位置：

- `config/api_profiles.json`

运行时（`/` 或 `/lab`）可在“API 配置档案”下拉框选择本次调用使用的档案；不选择时按当前 `.env` 环境运行。

## 4. Topic API 请求/响应（基础）

请求（POST JSON）核心字段：

- `text`: string
- `allowed_labels`: string[]
- `label_hints`: object[]
- `system_prompt`: string
- `output_contract`: object
- `rules.must_choose_from_allowed_labels`: true
- `rules.fallback_label`: `unknown_topic`

期望响应（JSON）：

```json
{
  "topic_label": "mathematics",
  "confidence": 0.82,
  "reason": "contains calculus and theorem signals"
}
```

约束：
- `topic_label` 必须在 `allowed_labels` 中。
- 若返回越界标签，系统会拒绝并降级。

## 5. Web Enrichment API 请求/响应（基础）

请求（POST JSON）核心字段：

- `snippets`: [{"source_name": string, "text": string}]
- `max_items`: number
- `required_fields`: ["title", "url", "purpose", "relevance_reason"]
- `system_prompt`: string
- `output_contract`: object
- `rules.supplementary_only`: true
- `rules.do_not_override_user_content`: true

期望响应（JSON）：

```json
{
  "resources": [
    {
      "title": "Example resource",
      "url": "https://example.com",
      "purpose": "supplementary reference",
      "relevance_reason": "supports the source topic"
    }
  ]
}
```

## 5.1 Content-Type Classifier API 请求/响应（基础）

请求（POST JSON）核心字段：

- `text`: string
- `allowed_categories`: string[]（固定为项目已有 6 类）
- `system_prompt`: string
- `output_contract`: object
- `rules.must_choose_from_allowed_categories`: true
- `rules.fallback_category`: `unclassified`

期望响应（JSON）：

```json
{
  "category": "basic_concepts",
  "confidence": 0.86,
  "reason": "contains definition/explanation signals"
}
```

约束：
- `category` 必须来自 `allowed_categories`。
- 越界或异常将降级回本地规则分类。

## 5.2 Notes Organizer API 请求/响应（基础）

请求（POST JSON）核心字段：

- `categorized_notes`: object（按类聚合后的文本列表）
- `output_contract`: 固定四个列表字段
- `rules.only_use_user_material`: true
- `rules.do_not_invent_new_facts`: true

期望响应（JSON）：

```json
{
  "must_remember_concepts": ["..."],
  "high_priority_points": ["..."],
  "easy_to_confuse_points": ["..."],
  "next_reading_directions": ["..."]
}
```

## 5.3 Image OCR API 请求/响应（基础）

请求（POST JSON）核心字段（custom 风格）：

- `task`: `image_ocr`
- `mime_type`: string
- `image_base64`: string
- `system_prompt`: string
- `output_contract`: object
- `rules.extract_only`: true
- `rules.do_not_invent_text`: true

期望响应（JSON）：

```json
{
  "text": "从图片中提取出的文字"
}
```

说明：
- openai/deepseek 兼容风格下会走 chat-completions + image_url(data URI) 模式。
- 图片 API OCR 是可选增强，默认策略 `IMAGE_OCR_ENHANCE_MODE=auto`：
  - `fallback_only`：仅本地 OCR 失败/空文本时调用 API；
  - `auto`：本地失败/空文本，或本地结果过短时调用 API 并择优；
  - `prefer_api`：启用 API 协助时优先使用 API 结果。
- 仅在显式开启 API 协助时启用（CLI/UI/API 请求统一策略）。

## 6. 降级语义（已实现）

- Topic API 不可用/超时/返回非法标签：降级到 local 规则或 `unknown_topic`
- Content-Type Classifier API 不可用/超时/返回越界类别：降级到本地规则分类
- Notes Organizer API 不可用/超时/返回非法结构：降级到本地 Stage 3 整理
- Image OCR API 不可用/超时/返回空文本：降级回本地 OCR 结果或原有失败语义（不崩溃）
- Web Enrichment API 不可用/超时：降级到 local URL 提取或 off
- 所有降级都会记录 warnings，并汇入 `pipeline_notes`

## 6.1 API 协助触发策略（默认关闭，显式开启）

- 默认行为：即使配置了 API URL/KEY，系统仍按本地模式运行（不自动调用外部 API）。
- 显式开启方式：
  - CLI：`--enable-api-assist`
  - UI：勾选“启用 API 协助（可选）”
  - FastAPI/Flask：请求体 `enable_api_assist=true`
- 开启后会在 `topic_mode=auto` / `web_enrichment_mode=auto` 下允许 API 协助，
  同时保留失败降级语义（不崩溃）。

## 7. 快速验证命令

```bash
python3 app.py samples/demo.md --enable-api-assist --topic-mode api
python3 app.py samples/demo.md --enable-api-assist --enable-web-enrichment --web-enrichment-mode api
# 图片 OCR API 增强（当本地 OCR 不可用或抽取为空时触发）
python3 app.py samples/ingest_demo.png --enable-api-assist --output-dir outputs
```

如果没配置 API URL，你会看到：`请接入API后使用`。

可选增强参数：

- `--web-enrichment-api-retries <n>`：Web API 可恢复错误重试次数（默认 1）

## 8. 启动最小服务入口（FastAPI）

```bash
pip install -r requirements-api.txt
uvicorn service.api_server:app --host 0.0.0.0 --port 8000 --reload
```

可用端点：
- `GET /health`
- `POST /pipeline/run`
- `GET /pipeline/capabilities`

最小请求示例：

```json
{
  "inputs": ["samples/demo.md"],
  "output_dir": "outputs",
  "topic_mode": "auto",
  "enable_web_enrichment": false
}
```

## 9. 启动最小服务入口（Flask）

```bash
pip install -r requirements-flask.txt
python3 service/flask_server.py --host 0.0.0.0 --port 8001
```

可用端点：
- `GET /health`
- `POST /pipeline/run`
- `GET /pipeline/capabilities`
