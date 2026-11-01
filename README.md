# LinkNote

**把看过的链接，变成找得到、读得懂、能追溯的笔记。**

Turn Douyin videos and WeChat articles into source-linked Markdown notes.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-2563EB.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.3-0F766E)](RELEASE_NOTES.md)
[![Status](https://img.shields.io/badge/status-early%20stage-D97706)](#项目状态)

[快速开始](#快速开始) · [输出示例](examples/sample-note.md) · [使用指南](docs/USAGE.md) · [参与贡献](CONTRIBUTING.md) · [反馈问题](https://github.com/sanjing590888-lang/linknote/issues)

---

收藏夹里存下了一条视频、一篇文章，过几天却想不起里面讲了什么。

LinkNote 是一个面向中文内容的开源命令行工具。给它一条抖音视频或微信公众号文章链接，它会提取正文或转写口播，整理摘要，保存来源与附件，输出到你自己的 Markdown 笔记目录。适合学习摘记、内容研究，以及个人知识库积累。

```text
一条链接 → 获取文章 / 转写口播 → 整理笔记 → Markdown + 正文 + 附件
```

## 为什么用 LinkNote

| 能力 | 对你有什么用 |
| --- | --- |
| **保留来源** | 笔记包含来源链接、作者与抓取时间，原始正文或转写另存，便于回看。 |
| **整理图文与口播** | 公众号提取正文并尝试下载图片；抖音通过音频转写整理视频内容。 |
| **按需使用模型** | 公众号仅提取无需 API 密钥；模型摘要可选，未配置时使用标注清楚的抽取式摘要。 |
| **处理重复任务** | 满足条件时跳过已完成任务；缺少原片或摘要时按记录补做，复用已有结果。 |
| **保护手改笔记** | 检测到笔记被手工修改时另存重跑结果；强制重跑未修改笔记时先备份。 |
| **文件由你管理** | 输出标准 Markdown，也支持 Obsidian callout；文件可放入普通文件夹或自己的知识库。 |

## 当前支持

| 内容来源 | 获取方式 | 需要准备 |
| --- | --- | --- |
| 微信公众号单篇文章 | 正文提取、图片本地化、可选摘要 | Python；仅提取无需模型服务 |
| 抖音单条公开视频 | 浏览器获取、下载音频所需媒体、ASR 转写、可选摘要 | Playwright 浏览器、FFmpeg、ASR 服务配置 |
| 模型摘要（可选） | 对获取的正文或转写进行整理 | LLM 服务配置 |

支持抖音短链接，也可传入包含链接的分享文案。当前面向单条内容处理，暂不支持批量账号采集、抖音图文提图或 OCR。

## 你会得到什么

一份笔记包含基本信息、摘要、关键观点、建议、正文或转写、附件与缺失项说明。原作者内容、算法整理和未核实信息会作区分。

> **结构示意，内容为虚构示例：**
>
> **标题：为什么要做笔记**  
> 来源、作者、抓取时间、处理状态  
> **摘要：** 把看过的内容变成日后能查询的资料。  
> **关键观点：** 记录“我准备怎么用”，比单纯增加收藏数量更有意义。  
> **正文 / 自动转写：** 单独保留，供核对摘要。  
> **处理说明：** 标注转写方式、摘要方式与未完成步骤。

[查看完整示例笔记 →](examples/sample-note.md)

```text
my-notes/
├── notes/          # 阅读用的 Markdown 笔记
├── raw/            # 正文或自动转写
├── attachments/    # 下载成功的公众号图片
├── media/          # 按需保留的原视频
└── .linknote/      # 任务状态、缓存和日志
```

## 快速开始

需要 **Python 3.10+**。先克隆仓库；不使用 Git 时，也可通过仓库的 **Code → Download ZIP** 下载并解压源码。

```bash
git clone https://github.com/sanjing590888-lang/linknote.git
cd linknote
```

### 1. 安装

<details open>
<summary>macOS / Linux</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

</details>

<details>
<summary>Windows PowerShell</summary>

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

下文的 `python` 替换为 `.\.venv\Scripts\python.exe`，`linknote` 替换为 `.\.venv\Scripts\python.exe -m linknote`。无需修改 PowerShell 执行策略。

</details>

### 2. 先保存一篇公众号文章

把占位内容换成实际文章链接。这个流程不需要 ASR 或 LLM 密钥：

```bash
linknote ingest "<微信公众号文章链接>" --extract-only --output ./my-notes
```

完成后，根据命令返回的路径打开笔记。网站访问条件或文章内容可能影响结果；处理状态会说明是否完整完成。

### 3. 处理抖音视频（可选）

安装浏览器依赖，并确保系统已安装 FFmpeg：

```bash
python -m pip install -e ".[douyin]"
python -m playwright install chromium
ffmpeg -version
```

在 `.env` 填写 ASR 服务的 `BASE_URL`、`MODEL` 和 `API_KEY`，变量名称见 [.env.example](.env.example)，然后运行：

```bash
linknote ingest "<抖音分享链接>" --output ./my-notes
```

需要模型摘要时，再填写 `LINKNOTE_LLM_*` 配置。ASR 和模型服务可能收费，服务由你自行选择和配置；兼容性范围见[使用指南](docs/USAGE.md)。

## 常用操作

```bash
# 检查配置与依赖
linknote doctor

# 同时保留原视频
linknote ingest "<抖音链接>" --keep-media --output ./my-notes

# 写入 Obsidian 笔记目录
linknote ingest "<链接>" --dialect obsidian --output ./my-vault/linknote

# 返回 JSON，接入自己的脚本或 Agent 工作流
linknote ingest "<链接>" --json --output ./my-notes
```

完整参数、补做规则、`--force` 行为与退出码见[使用指南](docs/USAGE.md)。自动化应读取 JSON 的 `status`：**退出码 0 也可能表示 `partial`，不等于全部完成。**

## 项目状态

**0.1.3 · 早期版本，源码已公开。** 已有维护者平台实测和指定故障复核，尚无第三方独立安装试用，也尚未配置 CI。

| 验证范围 | 已有记录 |
| --- | --- |
| 离线测试 | 53 条通过；覆盖提取、存储、重跑、媒体保留与缓存等逻辑 |
| 维护者平台实测 | Hermes 在 macOS 执行抖音下载与真实 ASR、公众号提取及指定重跑场景 |
| Codex 独立复核 | Windows 离线测试、0.1.3 三项回归、公众号实链；13 张图片和 14 个相对链接通过 |
| 尚未覆盖 | 第三方独立安装；Codex 独立抖音与真实 ASR 端到端复测 |

离线测试不代表平台始终可用。平台页面、登录状态或访问限制变化，都可能影响结果。[查看版本记录 →](RELEASE_NOTES.md)

## 使用边界

- **摘要需要回看原文。** 自动转写可能出错；模型摘要目前只使用正文前 12,000 字符，长文可能遗漏后半部分。工具不做外部事实核查。
- **本地保存，按配置调用外部服务。** 启用 ASR 会发送音频到所配置的服务；启用 LLM 会发送正文。仅提取仍会访问来源网站与图片资源。
- **内容权利属于原权利人。** MIT 许可证覆盖项目代码，不授予来源文章、图片或视频的再分发权。使用时请遵守来源平台规则。
- **缺失项会保留说明。** 图片可能下载失败并保留远程链接；登录和验证码需由用户处理；正文缓存目前不会自动清理。

## 参与项目

欢迎提交能复现的问题、平台适配修复、文档改进和测试补充。反馈时请保留版本、命令和脱敏错误信息，移除密钥、Cookie 与无权分享的正文。

[贡献指南](CONTRIBUTING.md) · [提交问题](https://github.com/sanjing590888-lang/linknote/issues/new) · [阅读源码](linknote)

后续方向包括抖音图文、预演模式和重试队列；**这些能力尚未实现，暂无交付时间承诺。**

## License

[MIT](LICENSE) © LinkNote contributors. FFmpeg 由用户独立安装，遵守其自身许可证。

