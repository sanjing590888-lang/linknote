"""Markdown 笔记渲染。

三条硬规则写在这里，不在业务代码里散着：
1. 原作者表达 / 模型整理 / 外部核实 三类信息必须分开写；
2. 转写文本不能标成逐字原文；
3. 附件一律用相对路径，笔记挪到哪里都能打开。
"""
from __future__ import annotations

import datetime as dt

from .models import Content, Status
from .summarize import Digest

PLATFORM_LABEL = {"douyin": "抖音", "wechat": "微信公众号"}
SOURCE_LABEL = {
    "native_text": "平台原生正文",
    "subtitle": "平台字幕",
    "asr": "音频转写（ASR）",
    "none": "无（只有元信息）",
}


def _fmt_stats(stats: dict) -> str:
    rows = [f"| {k} | {v if v is not None else '—'} |" for k, v in stats.items()]
    if not rows:
        return ""
    return "| 指标 | 数值 |\n|---|---|\n" + "\n".join(rows)


def _md_rel(rel: str | None) -> str | None:
    """笔记在 notes/ 下：相对路径补 ../，反斜杠转正斜杠（Windows 也点得开）。"""
    if not rel:
        return None
    rel = rel.replace("\\", "/")
    if rel.startswith(("../", "./", "/")):
        return rel
    return "../" + rel


def render(content: Content, digest: Digest, *, raw_rel: str | None,
           media_rel: str | None, attach_rel: str | None,
           body_markdown: str | None = None,
           tool_version: str = "0.1.0",
           dialect: str = "plain", frontmatter: bool = True) -> str:
    status = content.status
    lines: list[str] = []

    # ---------- frontmatter ----------
    tags = ["linknote", PLATFORM_LABEL.get(content.platform, content.platform)]
    if digest.mode == "extractive":
        tags.append("摘要-抽取式")
    head: list[str] = []
    if frontmatter:
        head += [
            "---",
            f"title: {content.title}",
            f"source: {content.url_resolved}",
            f"platform: {content.platform}",
            f"author: {content.author}",
            f"published: {content.published_at or '未知'}",
            f"fetched: {content.fetched_at}",
            f"status: {status.value}",
            f"content_source: {content.source.value}",
            f"tags: [{', '.join(tags)}]",
            "---",
            "",
        ]
    head += [f"# {content.title}", ""]
    lines += head

    # ---------- 元信息 ----------
    rows = [
        ("原标题", content.title),
        ("作者 / 账号", content.author or "—"),
        ("平台", PLATFORM_LABEL.get(content.platform, content.platform)),
        ("原始链接", content.url_raw),
        ("解析后链接", content.url_resolved),
        ("发布时间", content.published_at or "未获取到"),
        ("抓取时间", content.fetched_at),
        ("内容获取方式", SOURCE_LABEL.get(content.source.value, content.source.value)),
        ("处理状态", {"complete": "完整完成", "partial": "部分完成",
                      "failed": "失败"}[status.value]),
    ]
    for key, value in (content.extras or {}).items():
        if key in ("完整文案", "正文 Markdown", "作者文案", "章节目录"):
            continue
        if value not in (None, "", []):
            rows.append((key, value))
    lines += ["## 基本信息", "", "| 字段 | 内容 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    lines.append("")

    if content.stats:
        lines += ["> 源内容发布时的互动数据（平台页面显示值，未独立核验）：", ""]
        lines.append(_fmt_stats(content.stats))
        lines.append("")

    # ---------- 平台原文文案 / 章节目录 ----------
    caption = (content.extras or {}).get("作者文案") or ""
    if caption:
        lines += ["## 作者文案（平台原文，不是视频口播）", ""]
        lines += ["> " + line if line.strip() else ">" for line in caption.splitlines()]
        lines.append("")

    chapters = (content.extras or {}).get("章节目录") or []
    if chapters:
        lines += ["## 章节目录（平台数据，作者自己标的时间点）", ""]
        for ch in chapters:
            item = f"- `{ch['time']}` **{ch['title']}**"
            if ch.get("detail"):
                item += f" —— {ch['detail']}"
            lines.append(item)
        lines.append("")

    # ---------- 摘要 ----------
    if digest.summary:
        label = ("模型整理（" + digest.model + "）" if digest.mode == "llm"
                 else "抽取式摘要（机械挑选原文句子，非模型生成）")
        lines += [f"## 摘要", "", f"*来源：{label}*", ""]
        lines += [f"- {s}" for s in digest.summary]
        lines.append("")

    # ---------- 关键观点 ----------
    if digest.keypoints:
        lines += ["## 关键观点", ""]
        lines += [f"{i}. {p}" for i, p in enumerate(digest.keypoints, 1)]
        lines.append("")

    # ---------- 可执行建议 ----------
    lines += ["## 可执行建议", ""]
    if digest.actions:
        lines += [f"- {a}" for a in digest.actions]
    else:
        lines.append("源内容没有给出明确可执行的步骤，这里不硬凑。")
    lines.append("")

    # ---------- 信息分层说明 ----------
    lines += [
        "## 信息分层说明",
        "",
        "| 层级 | 本笔记里的内容 | 可信度 |",
        "|---|---|---|",
        "| 原作者表达 | 「作者文案」「原文 / 转写」两节的全部文字 | 作者观点，未经独立核验 |",
        f"| 模型整理 | 摘要、关键观点{'、可执行建议' if digest.actions else ''}"
        f"（{('模型 ' + digest.model) if digest.mode == 'llm' else '抽取式算法'}） | 二手整理，可能失真 |",
        "| 外部核实信息 | 本笔记不含 | 第一版不做外部事实核查 |",
        "",
    ]
    if content.source.value == "asr":
        body = ("下面这段是**音频自动转写**，不是逐字准确的原文。错字、专有名词误听、"
                "漏句都可能存在；需要引用时请回到原视频核对，原始转写见 "
                f"`{raw_rel or 'raw/'}`。")
        if dialect == "obsidian":
            lines += ["> [!warning] 转写说明", f"> {body}", ""]
        else:
            lines += ["> **注意：这是音频自动转写，不是逐字原文。**", f"> {body}", ""]

    # ---------- 正文 ----------
    if body_markdown:
        lines += ["## 正文（原文，来自页面）", "", body_markdown, ""]
    elif content.text:
        heading = "## 原文 / 转写" if content.source.value != "asr" else "## 转写全文（ASR）"
        lines += [heading, ""]
        if content.text_note:
            lines += [f"*{content.text_note}*", ""]
        lines += ["> " + line if line.strip() else ">" for line in content.text.splitlines()]
        lines.append("")

    # ---------- 附件 ----------
    lines += ["## 附件", ""]
    if raw_rel:
        lines.append(f"- 原文 / 转写原始文件：[{raw_rel}]({_md_rel(raw_rel)})")
    if media_rel:
        lines.append(f"- 原视频：[{media_rel}]({_md_rel(media_rel)})")
    elif content.media_path:
        lines.append("- 原视频：按配置未长期保留（只用于抽音轨转写）")
    if attach_rel:
        lines.append(f"- 图片目录：[{attach_rel}/]({_md_rel(attach_rel)}/)")
    if not (raw_rel or media_rel or attach_rel):
        lines.append("- 无")
    lines.append("")

    # ---------- 处理说明 ----------
    issues = list(content.errors) + list(content.warnings) + list(digest.warnings)
    lines += ["## 处理说明 / 缺失项", ""]
    if issues:
        lines += [f"- {i}" for i in issues]
    else:
        lines.append("- 无缺失，内容完整。")
    lines += [
        "",
        f"*由 linknote {tool_version} 生成于 "
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}；"
        "正文版权归原作者，仅供个人学习与研究使用。*",
        "",
    ]
    return "\n".join(lines)
