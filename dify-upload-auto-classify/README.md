# Dify 上传文件自动分类

一个 WorkBuddy Skill：把 Dify 的 **Pipeline（流水线）类型知识库**改造成"上传文件自动分类、自动清洗、自动分段、免手填参数"。

## 解决什么问题

- 每次上传文件都要手填 `Delimiter` / `Max chunk length` / `Chunk overlap`？——改造后无需再填。
- PDF 传进知识库被切成上万个 1 字符碎片，机器人答不出？——清洗器自动合并碎片。
- 想按文件类型（征信 / 招标 / 合同 / 自定义）走不同清洗路线？——关键词识别 + 主体前缀自动补全。

## 安装

把整个 `dify-upload-auto-classify` 文件夹放到 `~/.workbuddy/skills/` 下即可。WorkBuddy 会自动识别 `SKILL.md`。

也可下载 `dist/dify-upload-auto-classify.zip` 解压后放入技能目录。

## 快速开始

```bash
python -m pip install requests playwright
python -m playwright install chromium

# 1. 复制配置模板并填写（详见 SKILL.md 的"使用前需提供的信息"）
cp assets/config.example.json config.json

# 2. 导出登录 Cookie
python scripts/get_cookies.py --url http://你的Dify地址 --out cookies.json

# 3. 探测流水线结构，确认节点识别正确
python scripts/inspect_pipeline.py --config config.json

# 4. 安装清洗器并发布（幂等，可重复运行）
python scripts/install_cleaner.py --config config.json

# 5. 端到端验证
python scripts/verify_pipeline.py --config config.json
```

## 使用前需要准备的信息

| 项 | 说明 |
|---|---|
| Dify 访问地址 | 如 `http://dify.example.com:8080` |
| 知识库 ID | 知识库页面 URL 中 `/datasets/` 后一段 |
| 流水线 ID | 流水线页面 URL 中最后一段 |
| 登录 Cookie | 运行 `get_cookies.py` 导出，或用环境变量 `DIFY_ACCESS_TOKEN` + `DIFY_CSRF_TOKEN` |
| 分段参数（可选） | 有默认值：800 字符 / 80 重叠 / `\n\n` 分隔 |
| 文档类型规则（可选） | 见 `assets/cleaning_rules.example.json`，可按业务增删 |

`config.json`、`cookies.json` 等含认证信息的文件已被 `.gitignore` 排除，不会上传。**请勿把真实 Cookie、API Key 提交到仓库。**

## 目录结构

```
dify-upload-auto-classify/
├── SKILL.md                       # 技能主文档（触发条件、工作流、定制）
├── scripts/
│   ├── dify_client.py             # 通用 API 客户端 + 节点发现（无环境硬编码）
│   ├── inspect_pipeline.py        # 结构探测
│   ├── install_cleaner.py         # 核心：装清洗器 + 固化参数 + 发布
│   ├── verify_pipeline.py         # 端到端验证
│   └── get_cookies.py             # 导出登录 Cookie
├── references/
│   ├── api_notes.md               # Console API 细节与四个踩坑根因
│   └── workflow_guide.md          # 改造原理、决策树、定制指南
├── assets/
│   ├── config.example.json        # 配置填写模板（全占位符）
│   └── cleaning_rules.example.json# 文档类型识别规则示例（全通用值）
└── .gitignore
```

## 适用版本

自托管 Dify 1.20.x 的 Pipeline 类型知识库。扫描版 PDF（无文字层）需先 OCR。

## License

MIT
