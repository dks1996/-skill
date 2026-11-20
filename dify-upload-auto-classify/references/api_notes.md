# Dify Console API 细节与踩坑记录

本文件记录改造 Pipeline 知识库时验证过的接口行为与故障根因。适用于自托管 Dify 1.20.x。

## 认证

- 所有 `/console/api/*` 接口（连 GET）都要求两个头，缺一返回 401：
  - `Authorization: Bearer <access_token>`
  - `X-CSRF-Token: <csrf_token>`
- 两者都来自登录后的浏览器 Cookie。`access_token` 是 JWT，`csrf_token` 是短字符串。
- `get_cookies.py` 用 Playwright 打开浏览器让人登录，再导出 context.cookies()，最省心。
- 不要用交互服务 API 的 `app-xxx` Key 去调 console 接口，两者不是一回事。

## 流水线草稿读写

- 读：`GET /console/api/rag/pipelines/{pipeline_id}/workflows/draft`
- 存：`POST .../workflows/draft`，body 必须包含 `graph`（nodes/edges/viewport）+ `features` + `hash`。
  - `hash` 从 GET 的返回里取，用于防并发冲突；版本过期会返回 409，需重读后再存。
  - body 不要塞 `rag_pipeline_variables` 之类顶层字段，会被忽略或引发 400。
- 发布：`POST .../workflows/publish`，body `{}`。
- **大 body 不要通过浏览器 eval/JS 注入**：`page.evaluate` 对超长字符串会抛 SyntaxError。用 Python requests 直连最稳。
- 判断改动是否生效，以"发布成功 + 刷新画布有新节点"为准。

## 节点识别

不同 Dify 版本节点的 `data.type` / `data.title` 略有差异，`discover()` 用包含匹配而非全等：

| 关键节点 | 识别依据 |
|---|---|
| 聚合器 | type 含 `aggregator`，或 title 含 `聚合`/`Aggregator` |
| 分段器 | tool_name 含 `chunk`，或 title 含 `Chunker`/`分段` |
| 知识库 | title 含 `Knowledge Base`/`知识库`，或 type 含 `knowledge-base`/`dataset` |
| 提取器 | title 含 `extract`/`提取` |
| 条件分支 | type 含 `if-else`/`condition`/`if` |

改造前务必先跑 `inspect_pipeline.py` 看实际 title；若没识别出来，调整 `dify_client.discover()`。

## 四个关键踩坑（都是真实故障根因）

### 1. `Variable ['rag','shared','max_chunk_length'] does not exist`
分段器原本引用共享变量 `rag.shared.*`，但草稿里 `rag_pipeline_variables` 为空 → 运行时变量不存在 → 上传报错。这正是"每次上传都要手填分段参数"的根因。
**解法**：把 delimiter / max_chunk_length / chunk_overlap_length / 两个 checkbox 全改为 `{"type":"constant","value":...}` 固定值。

### 2. 分段内容是字面量 `{{#clean-xxx.result#}}`
分段器的 `input_variable` 若写成 `{"type":"mixed","value":"{{#clean-xxx.result#}}"}`，不会被解析，入库的是这串文本本身。
**解法**：用 `{"type":"variable","value":["<清洗节点id>","result"]}`。

### 3. `Failed to read file ... Check FILES_URL is reachable from plugin runtime`
Dify Extractor 是插件，运行在独立容器，读不到主服务上传的文件（Docker 网络/FILES_URL 未配）。
**解法**：删掉该插件节点，把连线改到内置「文档提取器」（在主服务内运行）。若用户确实需要插件，则须在 docker 环境变量里正确配置 `FILES_URL` 指向可访问的主机地址。

### 4. 401 / 409
- 401 = 认证头缺失或 token 过期，重新导出 Cookie。
- 409 = 草稿 hash 过期，重新 GET 拿最新 hash 再 POST。

## PDF 被切碎的判断方法

- 知识库 → 文档详情看 `Chunks` 数与 `Avg. paragraph length`。
- 一个正常几十页的 PDF 若出现上万 chunk、平均段落长度 1 字符，就是解析失败，不能只看状态 `Available`。
- 本地可用 `pypdf` 抽取原文验证 PDF 本身是否有文字层；有文字层却被切碎，就是 Dify 解析器问题，用本技能的清洗器修复；无文字层（扫描件）需先 OCR。
