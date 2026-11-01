# 使用指南

把抖音视频或微信公众号文章链接，整理成有来源、可复核的 Markdown 笔记。支持正文提取、视频音频转写、可选模型摘要、图片本地化和重复任务处理。输出可放普通文件夹或 Obsidian。

**0.1.3 早期版本**：已有维护者平台实测、53 条离线测试和指定故障独立复核，尚未进行第三方独立安装试用。

[返回项目首页](../README.md)

## 安装

需要 Python 3.10+。解压源码，进入包含 `pyproject.toml` 的目录。

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

Windows PowerShell（不需要修改执行策略）：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

Windows 下文的 `python` 替换为 `.\.venv\Scripts\python.exe`，`linknote` 替换为 `.\.venv\Scripts\python.exe -m linknote`。

抖音需要在虚拟环境中额外安装浏览器：

```bash
python -m pip install -e ".[douyin]"
python -m playwright install chromium
```

转写还需要系统安装 FFmpeg，确保 `ffmpeg -version` 可用。macOS 可用 `brew install ffmpeg`，Debian/Ubuntu 可用 `sudo apt install ffmpeg`；Windows 从 [FFmpeg 官方下载页](https://ffmpeg.org/download.html)选择构建并将包含 ffmpeg.exe 的目录加入 PATH。

## 使用

仅提取公众号正文不需要 API 密钥：

```bash
linknote ingest "<微信公众号文章链接>" --extract-only --output ./my-notes
```

抖音口播需在 `.env` 配置 `LINKNOTE_ASR_BASE_URL`、`LINKNOTE_ASR_MODEL`、`LINKNOTE_ASR_API_KEY`：

```bash
linknote ingest "<抖音分享链接>" --output ./my-notes
```

配置示例使用硅基流动 SenseVoiceSmall；服务可用性与费用以提供方为准，其他兼容接口未经全部验证。配置 `LINKNOTE_LLM_BASE_URL`、`LINKNOTE_LLM_MODEL`、`LINKNOTE_LLM_API_KEY` 后启用模型摘要；未配置时采用明确标注的抽取式摘要。

默认读取运行目录的 `.env`，其他位置用 `--env-file` 指定：

```bash
linknote ingest "<链接>" --env-file /path/to/.env --output /path/to/notes
linknote doctor
```

`doctor` 是配置与依赖检查，不保证平台访问成功。

## 参数和重跑

| 参数 | 含义 |
|---|---|
| `--output` | 输出目录 |
| `--extract-only` | 不下载视频、不调用 ASR/LLM；优先于保留视频配置 |
| `--keep-media` / `--no-keep-media` | 覆盖本次原视频保留配置 |
| `--force` | 重新获取、转写和摘要，可能再次产生模型费用 |
| `--json` | 机器可读结果 |
| `--dialect obsidian` | 使用 Obsidian callout，默认标准 Markdown |
| `--no-frontmatter` | 不输出 YAML 元信息 |
| `--env-file` | 指定配置文件 |
| `-v` | 调试日志 |

已完成且满足本次需求的任务可以跳过；缺少原片或模型摘要时按记录补做。摘要缓存绑定正文哈希。手工修改过的笔记另存新版本；强制重跑未修改笔记时保留 `.md.bak`。请为输出使用专用子目录并备份重要笔记。

退出码：`0` 为 complete、partial 或 skipped，`1` 为 failed，`2` 为前置错误，`3` 为未预期异常。自动化应检查 `--json` 的 `status`，不能只凭退出码 0 判定完整成功。

## 输出与数据流向

```text
my-notes/
├── notes/          # Markdown 笔记
├── raw/            # 正文或 ASR 转写
├── attachments/    # 公众号图片
├── media/          # 按需保留的原视频
└── .linknote/      # 状态、正文/摘要缓存和日志
```

笔记保留来源、作者、抓取时间和缺失项，区分作者表达与算法整理，ASR 明确标为自动转写。不执行外部事实核查。

输出默认保存在本地。启用 ASR 会把音频发送到配置的转写服务；启用模型摘要会把正文发送到配置的模型服务。仅提取仍访问来源网站和图片资源。不要公开密钥、Cookie、运行缓存和无权再分发的正文媒体。MIT 仅覆盖项目代码。

## 已知限制

- 抖音需要浏览器环境；登录或人机验证由用户处理，工具不绕过验证码。
- 未取得口播时可能报告 failed；抖音图文提图与 OCR 不在本版范围。
- 图片下载可能失败并保留远程链接；纯图片文章可能无有效正文。
- 模型摘要目前仅使用正文前 12,000 字符，可能遗漏长文后半部分；以保存的正文为准。
- 正文缓存暂不自动清理；使用标准 Markdown，但未逐一验证其他软件的导入效果。
- 平台适配可能因页面改动和访问条件失效。

## 验证

- Hermes：macOS / Python 3.11，报告完成抖音下载与真实 ASR、公众号提取及指定重跑场景。
- Codex：Windows / Python 3.12，53 条离线测试通过，独立复现仅提取、force、摘要缓存一致性三项修复。
- Codex：公众号实链成功，13 张图片下载，14 个相对链接通过。
- Codex 本轮未独立复测抖音和真实 ASR；无第三方独立安装试用。模拟测试不计入平台端到端验证。

## 开发与反馈

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

测试默认拦截网络。反馈请附版本、系统、命令、status 和脱敏错误；不要附真实凭据或他人正文。

## 许可证

采用 [MIT](../LICENSE)。Python 依赖为 requests、可选 Playwright 和开发依赖 pytest；FFmpeg 独立安装并遵守自身许可证。仓库不打包 FFmpeg 二进制或抓取媒体。

