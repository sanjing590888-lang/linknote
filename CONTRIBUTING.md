# 参与 LinkNote

感谢你帮助 LinkNote 更好地处理真实链接。项目处于早期阶段，优先解决内容获取失败、数据丢失、错误跳过和结果不一致的问题。

## 报告问题

请在 [Issues](https://github.com/sanjing590888-lang/linknote/issues) 中先检查是否已有相同问题，然后提供：

- LinkNote 版本、操作系统与 Python 版本。
- 执行的命令、使用的参数，以及预期与实际结果。
- 返回的 `status`、错误码和必要的脱敏日志。
- 是否能稳定复现；如涉及平台内容，说明视频、普通文章或图片文章等类型。

不要提交 API 密钥、Cookie、完整 `.env`、私人路径或无权公开的文章与媒体。来源链接仅在适合公开分享时提供。

## 本地开发

从仓库根目录安装开发依赖：

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

请先按 [README](README.md#快速开始) 创建虚拟环境。Windows 未激活环境时，使用 `.\.venv\Scripts\python.exe` 替换 `python`。

测试默认拦截网络。真实平台测试需要自行准备浏览器、FFmpeg 和服务配置；不要让离线测试调用收费接口，也不要把平台实测的原始内容提交进仓库。

## 提交修改

1. Fork 仓库，并从最新 `main` 建立修改分支。
2. 一次 PR 聚焦一个问题，说明触发条件、修改后的行为与验证结果。
3. 修改流程逻辑时，增加能暴露原问题的回归测试；单纯文档修改无需添加测试。
4. 检查差异，确保没有密钥、运行缓存或真实用户内容。
5. 提交 PR，并区分离线测试、真实平台测试和未验证事项。

涉及新平台、大幅调整输出格式或缓存机制时，请先开 Issue 讨论兼容性与范围。

## 代码入口

| 目录 / 文件 | 职责 |
| --- | --- |
| `linknote/cli.py` | 命令行参数与退出状态 |
| `linknote/pipeline.py` | 内容处理与补做流程 |
| `linknote/adapters/` | 抖音、公众号适配 |
| `linknote/transcribe.py` | 音频转写 |
| `linknote/summarize.py` | 抽取式与模型摘要 |
| `linknote/note.py`、`store.py` | 笔记生成、存储与覆盖保护 |
| `tests/` | 离线测试与回归用例 |

项目采用 [MIT](LICENSE) 许可证。提交代码时请确保你有权贡献相关内容。

