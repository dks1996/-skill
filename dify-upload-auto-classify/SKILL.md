---
name: dify-upload-auto-classify
description: 把 Dify 的 Pipeline（流水线）类型知识库改造成"上传文件自动分类、自动清洗、自动分段、免手填参数"。当用户抱怨 Dify 知识库上传文件每次都要填 Delimiter/Max chunk length/Chunk overlap、或 PDF 被切成单字符碎片导致机器人答不出、或想按文件类型自动走不同清洗路线时，应使用本技能。适用于自托管 Dify 1.20+ 的 Pipeline 知识库。
agent_created: true
---

# Dify 上传文件自动分类（智能清洗流水线）

## Overview

本技能把 Dify 的 Pipeline 类型知识库改造成一条"上传即处理"的流水线：文件进入后自动识别类型（征信报告 / 招标文件 / 合同 / 通用），自动修复被 PDF 解析器切碎的单字符段落，自动规范化空白，按类型补充主体前缀，最后用固化的分段参数入库。改造完成后，使用者上传文件不再需要填写任何分段表单。

核心手段是通过 Dify 控制台 API 读写知识库的 RAG 流水线草稿并发布，插入一个 Python 类型的 Code 节点（智能清洗器），把分段器参数由共享变量引用改为固定常量。所有操作都可脚本化、可重复执行，不依赖界面拖拽。

## When to Use

在以下情形使用本技能：

- 用户说"Dify 每次上传文件都要我填 Delimiter / Max chunk length / Chunk overlap，能不能自动"。
- 用户说"PDF 传进知识库后机器人答不出"，排查发现文档被切成上万个 1 字符 chunk。
- 用户想"按文件类型自动走不同清洗路线"，而现有流水线只按扩展名换了提取器。
- 用户需要在多台 Dify 环境复刻同一套清洗规则。

不使用本技能的情形：普通（非 Pipeline）知识库；扫描版 PDF（无文字层，需先 OCR）；只想改单个文档的切片而不改造流水线。

## 使用前需使用者提供的信息

动手前，先把 `assets/config.example.json` 复制为 `config.json` 并填写。必填项只有 4 项，其余都有合理默认值：

| 配置项 | 是否必填 | 说明 | 获取位置 |
|---|---|---|---|
| `dify_base_url` | 必填 | Dify 控制台访问根地址，如 `http://192.168.x.x:8080` | 浏览器地址栏 |
| `dataset_id` | 必填 | 目标知识库 UUID | 知识库页面 URL 中 `/datasets/` 后一段 |
| `pipeline_id` | 必填 | 该知识库的流水线 UUID | 用 `scripts/inspect_pipeline.py --list` 自动发现，或流水线页 URL |
| `cookies_file` 或环境变量 | 必填 | 已登录 Dify 的 Cookie，用于认证 | 见下方"认证信息获取" |
| `chunk_params` | 可选 | 分段参数，含默认值 | 一般无需改 |
| `clean_rules` | 可选 | 文档类型识别关键词与前缀规则，含通用默认值 | 按业务增删类型 |
| `test_file` | 可选 | 端到端验证用的本地测试文件 | 用于运行 `verify_pipeline.py` |

**认证信息获取**（Console API 需要 `access_token` + `csrf_token`，缺一不可）：

1. 推荐：运行 `python scripts/get_cookies.py --url <dify_base_url> --out cookies.json`，脚本打开浏览器，使用者登录后自动导出 Cookie 到文件，然后在 `config.json` 里把 `cookies_file` 指向它。
2. 或：使用者在浏览器登录 Dify 后，从开发者工具 Application → Cookies 复制 `access_token` 与 `csrf_token`，设为环境变量 `DIFY_ACCESS_TOKEN` / `DIFY_CSRF_TOKEN`。
3. 也可复用已有的 Playwright storage_state（含 cookies 数组），`cookies_file` 直接指向该 json。

不要把这些 Cookie、Token 写进仓库或日志。仓库自带的 `.gitignore` 已排除 `config.json`、`cookies.json`、`*.state.json`。

## Workflow

### 第 1 步：安装依赖

```bash
python -m pip install requests playwright
python -m playwright install chromium   # get_cookies.py / verify_pipeline.py 需要
```

### 第 2 步：探测流水线结构

```bash
python scripts/inspect_pipeline.py --config config.json
```

脚本读取流水线草稿，打印所有节点的 id / type / title，以及自动识别出的关键节点（聚合器、分段器、知识库、提取器、条件分支）和分段器当前参数。确认识别结果正确后再改造。若某类节点没识别出来，按 `references/api_notes.md` 的节点识别说明调整 `scripts/dify_client.py` 中的匹配规则。

### 第 3 步：安装智能清洗器

```bash
python scripts/install_cleaner.py --config config.json
```

脚本做以下事情（全部通过 API，幂等可重复运行）：

1. 读取最新草稿（自动取 hash，避免版本冲突）。
2. 找到或新建 Code 节点「智能清洗器」，把清洗代码写入（代码由 `clean_rules` 生成）。
3. 把清洗器输入变量绑定到聚合器输出。
4. 改连线：聚合器 → 智能清洗器 → 分段器 → 知识库。
5. 把分段器的 `input_variable` 改为引用清洗器结果，并把分段参数固化为常量。
6. 若发现会报 FILES_URL 错误的 Dify Extractor 插件节点，改连到内置文档提取器。
7. 保存草稿并发布。

执行后核对打印的节点列表和连线摘要。详细说明见 `references/workflow_guide.md`。

### 第 4 步：端到端验证（可选但推荐）

```bash
python scripts/verify_pipeline.py --config config.json --file /path/to/fragment_test.txt
```

脚本模拟上传一个"每行一个字符"的碎片文件，等待索引完成，检查生成的 chunk 数量与内容。若一个碎片文件变成少量正常段落且带正确前缀，说明流水线生效。也可手工在控制台上传文件 → Documents → 查看该文档的 Chunks 数与平均段落长度；1 字符/段落即为失败。

### 第 5 步：日常使用

改造完成后，使用者只需：知识库 → Documents → Add file → 选文件 → Next → Save & Process。界面上出现的 CHUNK SETTINGS 是只读折叠区，不需要填任何东西。

## Customization

- 增删文档类型：编辑 `config.json` 的 `clean_rules.types`，每项含 `name` / `label` / `keywords` / `add_subject_prefix` / `default_subject`。重新运行第 3 步即可。
- 调分段大小：改 `chunk_params`，重新运行第 3 步。
- 更换清洗算法：直接改 `scripts/install_cleaner.py` 中的 `render_clean_code()`。

## Troubleshooting

常见问题与根因见 `references/api_notes.md`，重点包括：共享变量未初始化导致 `Variable does not exist`、`input_variable` 引用格式错误导致分段内容是字面量、Dify Extractor 插件容器读不到文件、401 认证失败、409 草稿版本冲突。

## Resources

- `scripts/dify_client.py`：通用客户端，认证、读写草稿、发布、节点发现（无环境硬编码）。
- `scripts/inspect_pipeline.py`：结构探测。
- `scripts/install_cleaner.py`：核心改造脚本。
- `scripts/verify_pipeline.py`：端到端验证。
- `scripts/get_cookies.py`：辅助导出登录 Cookie。
- `references/api_notes.md`：Dify Console API 细节与踩坑记录。
- `references/workflow_guide.md`：改造原理、决策树、定制指南。
- `assets/config.example.json`：使用者填写模板。
- `assets/cleaning_rules.example.json`：文档类型识别规则示例。
