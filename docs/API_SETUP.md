# API_SETUP

Last Updated: 2026-04-21

本文件只说明当前仓库已实现的最基础 API 接入方式。

## 1. 当前支持的 API 接入点

- Topic Coarse Classifier API（`tools/topic_coarse_classify.py`）
- Web Enrichment API（`tools/web_enrichment.py`）

两者都是可选协助模式。
未接入 API 时，系统会自动降级，不会中断主流程。

另外，仓库已提供最小 FastAPI 服务入口：`service/api_server.py`。

## 2. 环境配置

1. 复制模板：

```bash
cp .env.example .env
```

2. 填写 `.env`（推荐使用统一 API 配置）：

```dotenv
KNOWLEDGEHARNESS_API_URL=https://your-shared-api.example.com/infer
KNOWLEDGEHARNESS_API_KEY=your_token_if_needed
```

说明：
- `app.py` 会自动读取项目根目录 `.env`。
- 若你在系统环境中已设置同名变量，`.env` 不会覆盖已有值。
- 当用户选择 `--topic-mode api` 或 `--web-enrichment-mode api` 但 URL 未配置时，CLI 会提示：`请接入API后使用`。
- 如需按模块覆盖，可额外设置：
  - `TOPIC_CLASSIFIER_API_URL` / `TOPIC_CLASSIFIER_API_KEY`
  - `WEB_ENRICHMENT_API_URL` / `WEB_ENRICHMENT_API_KEY`
  - 覆盖变量留空时自动回退统一配置。

## 3. 默认请求格式文件

默认模板文件：

- `config/api_payload_templates.json`

它定义了两类模板：
- `topic_classifier.system_prompt` + `output_contract`
- `web_enrichment.system_prompt` + `output_contract`

可通过环境变量替换模板路径：
- `TOPIC_CLASSIFIER_API_TEMPLATE`
- `WEB_ENRICHMENT_API_TEMPLATE`

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

## 6. 降级语义（已实现）

- Topic API 不可用/超时/返回非法标签：降级到 local 规则或 `unknown_topic`
- Web Enrichment API 不可用/超时：降级到 local URL 提取或 off
- 所有降级都会记录 warnings，并汇入 `pipeline_notes`

## 7. 快速验证命令

```bash
python3 app.py samples/demo.md --topic-mode api
python3 app.py samples/demo.md --enable-web-enrichment --web-enrichment-mode api
```

如果没配置 API URL，你会看到：`请接入API后使用`。

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
