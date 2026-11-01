from linknote.html2md import html_to_markdown, html_to_text
from linknote.models import Content, Source
from linknote.note import render
from linknote.summarize import Digest, extractive


def _content(source=Source.ASR):
    return Content(
        platform="douyin", content_id="770", title="随便聊聊 token",
        author="某某", url_raw="https://v.douyin.com/x/",
        url_resolved="https://www.douyin.com/video/770",
        published_at="2026-10-30 19:20", fetched_at="2026-11-01 20:00",
        source=source,
        text="第一句话讲的是这个概念很重要。第二个句子给出了具体数字 30% 到 60%。第三句说要注意区分官方口径和实测。",
    )


def test_render_has_required_sections():
    c = _content()
    note = render(c, extractive(c.text), raw_rel="raw/770_content.txt",
                  media_rel=None, attach_rel=None)
    for section in ("## 基本信息", "## 摘要", "## 关键观点", "## 可执行建议",
                    "## 信息分层说明", "## 附件", "## 处理说明 / 缺失项"):
        assert section in note
    assert "2026-10-30 19:20" in note
    assert "raw/770_content.txt" in note


def test_asr_gets_warning_block():
    c = _content(Source.ASR)
    note = render(c, extractive(c.text), raw_rel="raw/770_content.txt",
                  media_rel=None, attach_rel=None)
    assert "音频自动转写" in note
    assert "不是逐字准确" in note


def test_native_text_has_no_asr_warning():
    c = _content(Source.NATIVE_TEXT)
    note = render(c, extractive(c.text), raw_rel="raw/770_content.txt",
                  media_rel=None, attach_rel=None)
    assert "不是逐字准确" not in note


def test_plain_dialect_has_no_obsidian_callout():
    c = _content(Source.ASR)
    note = render(c, extractive(c.text), raw_rel=None, media_rel=None, attach_rel=None)
    assert "[!warning]" not in note
    assert "**注意：这是音频自动转写，不是逐字原文。**" in note


def test_obsidian_dialect_uses_callout():
    c = _content(Source.ASR)
    note = render(c, extractive(c.text), raw_rel=None, media_rel=None, attach_rel=None,
                  dialect="obsidian")
    assert "> [!warning] 转写说明" in note


def test_frontmatter_can_be_disabled():
    c = _content()
    note = render(c, extractive(c.text), raw_rel=None, media_rel=None,
                  attach_rel=None, frontmatter=False)
    assert not note.startswith("---")
    assert note.startswith("# ") or note.lstrip().startswith("#")


def test_frontmatter_default_on():
    c = _content()
    note = render(c, extractive(c.text), raw_rel=None, media_rel=None, attach_rel=None)
    assert note.startswith("---\ntitle: ")
    assert "tags: [linknote, 抖音" in note


def test_actions_not_invented_when_absent():
    c = _content()
    d = Digest(mode="extractive", summary=["摘要一"], keypoints=["观点一"], actions=[])
    note = render(c, d, raw_rel=None, media_rel=None, attach_rel=None)
    assert "源内容没有给出明确可执行的步骤" in note


def test_caption_and_chapters_render():
    c = _content()
    c.extras["作者文案"] = "这是作者写在简介里的说明。\n另有第二行。"
    c.extras["章节目录"] = [
        {"time": "00:00", "title": "引言", "detail": ""},
        {"time": "00:17", "title": "申请流程", "detail": "需要另外审核。"},
    ]
    note = render(c, extractive(c.text), raw_rel=None, media_rel=None, attach_rel=None)
    assert "## 作者文案（平台原文，不是视频口播）" in note
    assert "这是作者写在简介里的说明。" in note
    assert "## 章节目录" in note
    assert "`00:17` **申请流程** —— 需要另外审核。" in note
    # 这两项不应该混进基本信息表
    assert "| 作者文案 |" not in note


def test_html2md_handles_wechat_markup():
    html = ('<section><p>第一段<strong>加粗</strong>。</p>'
            '<p><img data-src="https://mmbiz.qpic.cn/a.jpg" /></p>'
            '<ul><li>要点一</li><li>要点二</li></ul></section>')
    md = html_to_markdown(html, {"https://mmbiz.qpic.cn/a.jpg": "img_01.jpg"})
    assert "**加粗**" in md
    assert "![](img_01.jpg)" in md
    assert "- 要点一" in md


def test_html_to_text_drops_tags():
    assert html_to_text("<p>你好<br>世界</p>").strip() == "你好\n世界"
